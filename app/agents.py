"""Agent-orkestratie met LangGraph.

    vraag
      │
  [analyse]      embedding + herkende HiX-concepten (+ gerelateerde concepten uit de graaf)
      │
  [router]       kiest 1..max_agents modules (concepten + similarity met modulebeschrijving)
      │  fan-out (parallel, LangGraph Send)
  [module_agent] per module/werkgroep: eigen retrieval-scope + eigen instructie
      │  fan-in
  [synthese]     voegt deelantwoorden samen, bepaalt betrouwbaarheid, bronnen, escalatie
      │
   antwoord

De router is bewust deterministisch (geen LLM-call): op CPU scheelt dat tijd en het
maakt routering uitlegbaar in de demo.
"""
from __future__ import annotations

import operator
import time
from typing import Annotated, Any, TypedDict

import numpy as np
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from .config import thresholds
from .faq import DynamicFAQ
from .graph_store import GraphStore
from .ingest import ConceptMatcher
from .llm import Chat, Embedder
from .retrieval import format_context, retrieve

ALGEMEEN = "Algemeen"

AGENT_SYSTEM = """Je bent de {module}-expert van de {werkgroep} in een ziekenhuis en ondersteunt functioneel beheerders en key-users bij vragen over het EPD HiX.

Regels:
- Gebruik UITSLUITEND de aangeleverde context. Verzin geen schermen, knoppen of toestelnummers.
- Ziekenhuisspecifieke werkinstructies gaan voor op standaarddocumentatie; benoem het als ze afwijken.
- Verwijs naar bronnen met hun nummer, bijvoorbeeld [2].
- Is de context onvoldoende? Zeg dat eerlijk en stel één verduidelijkende vraag.
- Antwoord beknopt in het Nederlands, in deze structuur:

**Waarschijnlijke oorzaak:** ...
**Oplossing:**
1. ...
**Lokale afspraken:** ... (alleen als een ziekenhuisspecifieke bron iets zegt)
"""

SYNTH_SYSTEM = """Je voegt deelantwoorden van verschillende module-experts samen tot één helder advies voor een functioneel beheerder.
Behoud bronverwijzingen zoals [1] en de structuur (Waarschijnlijke oorzaak / Oplossing / Lokale afspraken).
Laat tegenstrijdigheden zien in plaats van ze weg te poetsen. Verzin niets. Antwoord in het Nederlands."""


class State(TypedDict, total=False):
    question: str
    q_emb: Any
    concepts: list[str]
    related: list[str]
    routes: list[dict]
    modules: list[str]
    module: str                                   # alleen in de Send-payload naar een module-agent
    agent_results: Annotated[list[dict], operator.add]
    answer: str
    confidence: str
    sources: list[dict]
    escalate: bool


class ExpertAgent:
    def __init__(self, cfg: dict, store: GraphStore, embedder: Embedder, chat: Chat, faq: DynamicFAQ | None = None):
        self.cfg, self.store, self.embedder, self.chat, self.faq = cfg, store, embedder, chat, faq
        self.th = thresholds(cfg)
        self.matcher = ConceptMatcher(cfg["concepts"])
        self.module_names = list(cfg["modules"])
        self.module_embs = embedder.embed([f"{m}: {cfg['modules'][m]['beschrijving']}" for m in self.module_names])
        self.graph = self._build()

    # ------------------------------------------------------------ graph
    def _build(self):
        g = StateGraph(State)
        g.add_node("analyse", self._analyse)
        g.add_node("router", self._route)
        g.add_node("module_agent", self._module_agent)
        g.add_node("synthese", self._synthesize)
        g.add_edge(START, "analyse")
        g.add_edge("analyse", "router")
        g.add_conditional_edges("router", self._fan_out, ["module_agent"])
        g.add_edge("module_agent", "synthese")
        g.add_edge("synthese", END)
        return g.compile()

    def _analyse(self, s: State) -> dict:
        q_emb = self.embedder.embed([s["question"]])[0]
        concepts = self.matcher.find(s["question"])
        return {"q_emb": q_emb, "concepts": concepts, "related": self.store.related_concepts(concepts, 5)}

    def _route(self, s: State) -> dict:
        sims = self.module_embs @ np.asarray(s["q_emb"], dtype=np.float32)
        votes = {m: 0 for m in self.module_names}
        for m in self.matcher.modules_for(s["concepts"]):
            votes[m] = votes.get(m, 0) + 1
        routes = sorted(
            ({"module": m, "similarity": round(float(sims[i]), 3), "concept_votes": votes[m],
              "score": round(float(sims[i]) + 0.15 * votes[m], 3)} for i, m in enumerate(self.module_names)),
            key=lambda r: -r["score"],
        )
        top = routes[0]
        if top["concept_votes"] == 0 and top["similarity"] < self.th["router_min"]:
            return {"routes": routes, "modules": [ALGEMEEN]}
        chosen = [top["module"]]
        for r in routes[1 : self.cfg["orchestration"]["max_agents"]]:
            # Tweede agent alleen als die module ook concepten raakt én dicht bij de top zit.
            if r["concept_votes"] > 0 and r["score"] >= top["score"] - 0.2:
                chosen.append(r["module"])
        return {"routes": routes, "modules": chosen}

    def _fan_out(self, s: State) -> list[Send]:
        return [Send("module_agent", {**s, "module": m}) for m in s["modules"]]

    def _module_agent(self, s: State) -> dict:
        module = s["module"]
        scope = None if module == ALGEMEEN else [module]
        hits = retrieve(self.store, s["q_emb"], s["concepts"] + s.get("related", [])[:2], scope, self.cfg)
        werkgroep = self.cfg["modules"].get(module, {}).get("werkgroep", "functioneel beheer")
        # Unieke bronnummers per agent, zodat [n] ook na synthese eenduidig is.
        start = s["modules"].index(module) * self.cfg["retrieval"]["top_k"] + 1
        if not hits:
            answer = "Ik vind in de kennisbank geen informatie over deze vraag."
        else:
            answer = self.chat.chat(
                AGENT_SYSTEM.format(module=module, werkgroep=werkgroep),
                f"VRAAG: {s['question']}\n\nCONTEXT:\n{format_context(hits, start)}",
            )
        return {"agent_results": [{"module": module, "werkgroep": werkgroep, "answer": answer, "hits": hits, "start": start}]}

    def _synthesize(self, s: State) -> dict:
        results = sorted(s["agent_results"], key=lambda r: r["start"])
        all_hits = [h for r in results for h in r["hits"]]
        if len(results) == 1:
            answer = results[0]["answer"]
        else:
            parts = "\n\n".join(f"--- Deelantwoord {r['module']} ({r['werkgroep']}) ---\n{r['answer']}" for r in results)
            context = "\n\n".join(format_context(r["hits"], r["start"]) for r in results)
            answer = self.chat.chat(SYNTH_SYSTEM, f"VRAAG: {s['question']}\n\n{parts}\n\nCONTEXT:\n{context}")
        confidence = self._confidence(all_hits)
        escalate = confidence == "laag"
        if escalate:
            answer += ("\n\n> ⚠️ Lage betrouwbaarheid: in het volledige platform zou deze vraag nu worden uitgezet "
                       "in de community (eigen organisatie / regio / expertgroep).")
        return {"answer": answer, "confidence": confidence, "escalate": escalate, "sources": self._sources(results)}

    # ------------------------------------------------------------ helpers
    def _confidence(self, hits: list[dict]) -> str:
        if not hits:
            return "laag"
        cos = sorted((h["cosine"] for h in hits), reverse=True)
        support = sum(1 for c in cos if c >= self.th["confidence_low"])
        if cos[0] >= self.th["confidence_high"] and support >= 2:
            return "hoog"
        if cos[0] >= self.th["confidence_low"]:
            return "middel"
        return "laag"

    @staticmethod
    def _sources(results: list[dict]) -> list[dict]:
        out = []
        for r in results:
            for i, h in enumerate(r["hits"], r["start"]):
                out.append({"agent": r["module"], "nr": i, "titel": h["titel"], "sectie": h["sectie"],
                            "bron": h["bron"], "type": h["type"], "module": h["module"],
                            "cosine": round(h["cosine"], 3), "score": round(h["score"], 3),
                            "via": h["via"], "concepten": h.get("concepten") or [], "tekst": h["tekst"]})
        return out

    # ------------------------------------------------------------ publieke API
    def ask(self, question: str, use_faq: bool = True, record_faq: bool = True) -> dict:
        t0 = time.time()
        if use_faq and self.faq is not None:
            q_emb = self.embedder.embed([question])[0]
            row, sim = self.faq.nearest(q_emb)
            if row is not None and sim >= self.th["faq_shortcut"]:
                self.faq.record(question, q_emb, row["antwoord"], row["betrouwbaarheid"], row["module"])
                return {"question": question, "answer": row["antwoord"], "confidence": row["betrouwbaarheid"],
                        "from_faq": True, "faq_id": row["id"], "faq_similarity": round(sim, 3),
                        "modules": [row["module"]], "routes": [], "concepts": [], "related": [],
                        "sources": [], "agents": [], "escalate": False, "seconds": round(time.time() - t0, 2)}

        out = self.graph.invoke({"question": question})
        result = {
            "question": question, "answer": out["answer"], "confidence": out["confidence"], "from_faq": False,
            "modules": out["modules"], "routes": out["routes"], "concepts": out["concepts"],
            "related": out.get("related", []), "sources": out["sources"], "escalate": out["escalate"],
            "agents": [{"module": r["module"], "werkgroep": r["werkgroep"], "answer": r["answer"]}
                       for r in out["agent_results"]],
        }
        if record_faq and self.faq is not None:
            titles = list(dict.fromkeys(src["titel"] for src in out["sources"][:3]))
            result["faq"] = self.faq.record(question, out["q_emb"], out["answer"], out["confidence"],
                                            out["modules"][0], titles)
        result["seconds"] = round(time.time() - t0, 2)
        return result


def build_agent(cfg: dict) -> ExpertAgent:
    from .graph_store import make_store
    from .llm import make_chat, make_embedder

    return ExpertAgent(cfg, make_store(cfg), make_embedder(cfg), make_chat(cfg), DynamicFAQ.from_config(cfg))
