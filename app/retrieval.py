"""Hybride GraphRAG-retrieval.

1. Vector search (semantisch), optioneel beperkt tot de module(s) van de agent.
2. Graaf-expansie via concepten: chunks die dezelfde HiX-begrippen noemen als de vraag.
3. Graaf-expansie via VERFIJNT: bij een standaarddoc ook de lokale werkinstructie ophalen
   (en andersom) – ook over modulegrenzen heen.
4. Fusie-score: cosine + bonus voor gedeelde concepten + bonus voor ziekenhuisspecifieke kennis.
"""
from __future__ import annotations

import numpy as np

from .graph_store import GraphStore, Hit


def retrieve(store: GraphStore, q_emb: np.ndarray, q_concepts: list[str], modules: list[str] | None,
             cfg: dict) -> list[Hit]:
    r = cfg["retrieval"]
    q = np.asarray(q_emb, dtype=np.float32)
    cands: dict[str, Hit] = {}

    def add(hits: list[Hit], via: str) -> None:
        for h in hits:
            if h["chunk_id"] in cands:
                cands[h["chunk_id"]]["via"].add(via)
            else:
                cands[h["chunk_id"]] = {**h, "via": {via}}

    vec_hits = store.vector_search(q, r["vector_candidates"], modules)
    add(vec_hits, "vector")
    add(store.chunks_for_concepts(q_concepts, modules, limit=10), "concept")
    if r.get("refine_expansion"):
        top_docs = list(dict.fromkeys(h["doc_id"] for h in vec_hits[:3]))
        add(store.refined_chunks(top_docs, limit=12), "verfijnt")

    qc = set(q_concepts)
    for h in cands.values():
        emb = np.asarray(h.pop("embedding"), dtype=np.float32)
        h["cosine"] = float(emb @ q)
        overlap = len(qc & set(h.get("concepten") or []))
        h["score"] = (h["cosine"] + r["concept_bonus"] * overlap
                      + (r["local_bonus"] if h["bron"] == "ziekenhuis" else 0.0))
        h["via"] = sorted(h["via"])
    ranked = sorted(cands.values(), key=lambda h: -h["score"])
    return ranked[: r["top_k"]]


def format_context(hits: list[Hit], start: int = 1) -> str:
    blocks = []
    for i, h in enumerate(hits, start):
        label = "ZIEKENHUISSPECIFIEK" if h["bron"] == "ziekenhuis" else "standaard HiX-documentatie"
        blocks.append(f"### [{i}] {h['titel']} – {h['sectie']} ({label}, {h['type']}, versie {h['versie']})\n{h['tekst']}")
    return "\n\n".join(blocks)
