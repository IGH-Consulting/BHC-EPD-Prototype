"""Ingestie: markdown-bronnen -> chunks -> embeddings + concepten -> kennisgraaf.

Waarom geen volledige LLM-graph-extractie (zoals Microsoft GraphRAG)?
Op een CPU-laptop met een 3B-model is dat traag en onbetrouwbaar. De graaf wordt
daarom opgebouwd uit wat we zeker weten (documentstructuur, metadata, VERFIJNT-relaties)
plus een begrippenlijst. LLM-extractie is optioneel aan te zetten als verrijking.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from .config import resolve
from .graph_store import GraphStore
from .llm import Chat, Embedder


# ---------------------------------------------------------------- concepten
class ConceptMatcher:
    """Herkent concepten uit de begrippenlijst (inclusief synoniemen) in tekst."""

    def __init__(self, concepts: dict):
        self.concepts = concepts
        pairs = [(syn.lower(), name) for name, c in concepts.items() for syn in [name.lower(), *c.get("synoniemen", [])]]
        pairs.sort(key=lambda p: -len(p[0]))  # langste synoniem eerst
        self._patterns = [(re.compile(rf"(?<![\w-]){re.escape(s)}(?![\w-])", re.IGNORECASE), n) for s, n in pairs]

    def find(self, text: str) -> list[str]:
        found: list[str] = []
        for pat, name in self._patterns:
            if name not in found and pat.search(text):
                found.append(name)
        return found

    def modules_for(self, concepts: list[str]) -> list[str]:
        return [self.concepts[c]["module"] for c in concepts if c in self.concepts]


# ---------------------------------------------------------------- parsing & chunking
@dataclass
class Doc:
    meta: dict
    body: str


def parse_markdown(path: Path) -> Doc:
    raw = path.read_text(encoding="utf-8")
    meta: dict = {}
    if raw.startswith("---"):
        _, fm, raw = raw.split("---", 2)
        meta = yaml.safe_load(fm) or {}
    meta.setdefault("id", path.stem)
    meta.setdefault("titel", path.stem)
    meta.setdefault("bron", path.parent.name)
    meta.setdefault("type", "document")
    meta.setdefault("module", "Algemeen")
    meta.setdefault("versie", "onbekend")
    meta.setdefault("organisatie", None)
    meta.setdefault("verfijnt", [])
    meta["versie"] = str(meta["versie"])
    meta["pad"] = str(path)
    return Doc(meta, raw.strip())


def chunk_markdown(body: str, max_chars: int) -> list[tuple[str, str]]:
    """Splitst op ##-kopjes; te lange secties op alinea's. Geeft (sectie, tekst)."""
    sections: list[tuple[str, list[str]]] = [("Inleiding", [])]
    for line in body.splitlines():
        if line.startswith("> "):  # disclaimer-regels niet embedden
            continue
        if line.startswith("## "):
            sections.append((line[3:].strip(), []))
        elif line.startswith("# "):
            continue
        else:
            sections[-1][1].append(line)
    out: list[tuple[str, str]] = []
    for title, lines in sections:
        text = "\n".join(lines).strip()
        if not text:
            continue
        buf = ""
        for para in re.split(r"\n\s*\n", text):
            if buf and len(buf) + len(para) > max_chars:
                out.append((title, buf.strip()))
                buf = ""
            buf += para + "\n\n"
        if buf.strip():
            out.append((title, buf.strip()))
    return out


# ---------------------------------------------------------------- pipeline
LLM_CONCEPT_PROMPT = """Je extraheert kernbegrippen uit HiX/EPD-documentatie.
Geef JSON: {"concepten": ["...", "..."]} met maximaal 5 korte begrippen (functionaliteit, scherm, foutmelding, proces).
Gebruik bij voorkeur deze bestaande begrippen als ze passen: %s"""


def ingest(cfg: dict, store: GraphStore, embedder: Embedder, chat: Chat | None = None,
           reset: bool = True, log=print) -> dict:
    icfg = cfg["ingest"]
    matcher = ConceptMatcher(cfg["concepts"])
    files = sorted(p for src in icfg["sources"] for p in resolve(src["path"]).rglob("*.md"))
    if not files:
        raise FileNotFoundError("Geen .md-bestanden gevonden in de geconfigureerde bronnen.")

    dim = int(embedder.embed(["dimensie-test"]).shape[1])
    if reset:
        store.reset()
    store.ensure_schema(dim)
    store.upsert_domain(cfg["modules"], cfg["concepts"])

    n_chunks = 0
    for path in files:
        doc = parse_markdown(path)
        pieces = chunk_markdown(doc.body, icfg["chunk_max_chars"])
        # Contextuele embedding: titel + sectie meegeven verbetert retrieval merkbaar.
        embed_texts = [f"{doc.meta['titel']} – {sec}\n{txt}" for sec, txt in pieces]
        vecs = embedder.embed(embed_texts)
        chunks = []
        for i, ((sec, txt), vec) in enumerate(zip(pieces, vecs)):
            concepts = matcher.find(f"{sec}\n{txt}")
            if chat is not None and icfg.get("llm_concept_extraction"):
                concepts += _llm_concepts(chat, txt, list(cfg["concepts"]), concepts)
            chunks.append({"id": f"{doc.meta['id']}#{i}", "tekst": txt, "sectie": sec, "volgorde": i,
                           "embedding": vec, "concepten": concepts})
        store.add_document(doc.meta, chunks)
        n_chunks += len(chunks)
        log(f"  + {doc.meta['bron']:<10} {doc.meta['id']:<24} {len(chunks)} chunks")
    store.finalize()
    stats = store.stats()
    log(f"Klaar: {len(files)} documenten, {n_chunks} chunks. Graaf: {stats}")
    return stats


def _llm_concepts(chat: Chat, text: str, known: list[str], already: list[str]) -> list[str]:
    try:
        raw = chat.chat(LLM_CONCEPT_PROMPT % ", ".join(known), text, json_mode=True)
        found = json.loads(raw).get("concepten", [])
    except Exception:
        return []
    out = []
    for c in found:
        c = str(c).strip()
        match = next((k for k in known if k.lower() == c.lower()), c[:1].upper() + c[1:])
        if match and match not in already and match not in out and len(match) < 60:
            out.append(match)
    return out
