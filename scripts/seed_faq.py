"""Vul de FAQ met gesimuleerde vraaghistorie (laatste 60 dagen) om het verval te demonstreren.

    python scripts/seed_faq.py [--demo]
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import load_config  # noqa: E402
from app.faq import DynamicFAQ  # noqa: E402
from app.llm import make_embedder  # noqa: E402

# (vraag, dagen geleden dat hij gesteld werd)
HISTORY = [
    ("Wat betekent de melding Barcode niet herkend bij het toedienen?", [1, 2, 2, 4, 6, 9]),
    ("Welke middelen vereisen een dubbele controle?", [3, 5, 12, 20]),
    ("Waarom kan ik de opname niet afsluiten door openstaande orders?", [1, 8]),
    ("Hoe haal ik externe medicatiegegevens op bij opname?", [25, 30, 33, 40, 41, 45]),   # was populair, zakt weg
    ("Waarom wordt de vroege waarschuwingsscore niet berekend?", [55, 58]),                # oud, verdwijnt
    ("Wat moet ik doen bij een verzendfout van een labaanvraag?", [0.5]),                  # nieuw
]

p = argparse.ArgumentParser()
p.add_argument("--demo", action="store_true")
a = p.parse_args()
cfg = load_config(overrides={"backends": {"embedding": "hash"}} if a.demo else None)
faq = DynamicFAQ.from_config(cfg)
faq.clear()
emb = make_embedder(cfg)
now = time.time()
events = sorted(((now - d * 86400, q) for q, days in HISTORY for d in days))
vecs = dict(zip([q for q, _ in HISTORY], emb.embed([q for q, _ in HISTORY])))
for ts, q in events:
    faq.record(q, vecs[q], f"(gesimuleerd antwoord op: {q})", "hoog", now=ts)
print(f"{'score':>6}  {'zichtbaar':>9}  {'n':>2}  vraag")
for it in faq.top(now=now, include_hidden=True):
    print(f"{it['score']:6.2f}  {str(it['zichtbaar']):>9}  {it['n_gesteld']:>2}  {it['vraag']}")
