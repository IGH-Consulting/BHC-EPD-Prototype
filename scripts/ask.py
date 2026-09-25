"""Stel een vraag via de command line.

    python scripts/ask.py "Barcode niet herkend bij toedienen, wat nu?"
    python scripts/ask.py --demo "..."
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents import build_agent  # noqa: E402
from app.config import load_config  # noqa: E402

p = argparse.ArgumentParser()
p.add_argument("vraag")
p.add_argument("--demo", action="store_true")
p.add_argument("--no-faq", action="store_true", help="FAQ-shortcut overslaan")
a = p.parse_args()

over = {"backends": {"store": "memory", "embedding": "hash", "llm": "fake"}} if a.demo else None
agent = build_agent(load_config(overrides=over))
r = agent.ask(a.vraag, use_faq=not a.no_faq)
print(f"\nRoute: {r['modules']}  |  concepten: {r['concepts']}  |  betrouwbaarheid: {r['confidence']}"
      f"  |  {r['seconds']}s{'  |  uit FAQ' if r['from_faq'] else ''}\n")
print(r["answer"])
if r["sources"]:
    print("\nBronnen:")
    for s in r["sources"]:
        print(f"  [{s['nr']}] ({s['bron']}) {s['titel']} – {s['sectie']}  cos={s['cosine']} via={','.join(s['via'])}")
if r.get("faq"):
    print(f"\nFAQ: {r['faq']['actie']}")
