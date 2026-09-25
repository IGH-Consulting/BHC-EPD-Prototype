"""Laad de bronnen in de kennisgraaf.

    python scripts/ingest.py                      # volgens config.yaml (Neo4j + Ollama)
    python scripts/ingest.py --demo               # zonder Docker/modellen (memory + hash)
    python scripts/ingest.py --llm-concepts       # extra concepten via LLM (traag op CPU)
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import load_config  # noqa: E402
from app.graph_store import make_store  # noqa: E402
from app.ingest import ingest  # noqa: E402
from app.llm import make_chat, make_embedder  # noqa: E402

p = argparse.ArgumentParser()
p.add_argument("--demo", action="store_true", help="memory-store + hash-embeddings + fake LLM")
p.add_argument("--llm-concepts", action="store_true")
a = p.parse_args()

over = {"ingest": {"llm_concept_extraction": a.llm_concepts}}
if a.demo:
    over["backends"] = {"store": "memory", "embedding": "hash", "llm": "fake"}
cfg = load_config(overrides=over)
print(f"Backends: {cfg['backends']}")
store = make_store(cfg)
try:
    ingest(cfg, store, make_embedder(cfg), make_chat(cfg) if a.llm_concepts else None)
finally:
    store.close()
