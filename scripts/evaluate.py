"""Evalueer routering en retrieval op de gouden set en help drempels kalibreren.

    python scripts/evaluate.py [--demo]

Meet: routering-accuratesse, hit@k (verwacht document in de bronnen), en de
cosine-verdeling van de beste hit voor relevante vs. off-topic vragen.
Gebruikt geen LLM-antwoorden (alleen analyse/router/retrieval), dus snel op CPU.
"""
import argparse
import statistics
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents import ALGEMEEN, ExpertAgent  # noqa: E402
from app.config import ROOT, load_config, thresholds  # noqa: E402
from app.graph_store import make_store  # noqa: E402
from app.llm import FakeChat, make_embedder  # noqa: E402
from app.retrieval import retrieve  # noqa: E402

p = argparse.ArgumentParser()
p.add_argument("--demo", action="store_true")
a = p.parse_args()
cfg = load_config(overrides={"backends": {"store": "memory", "embedding": "hash", "llm": "fake"}} if a.demo else None)
agent = ExpertAgent(cfg, make_store(cfg), make_embedder(cfg), FakeChat())
cases = yaml.safe_load(open(ROOT / "data" / "eval_vragen.yaml", encoding="utf-8"))

route_ok = hits_ok = n_rel = 0
cos_rel, cos_off = [], []
for c in cases:
    s = agent._analyse({"question": c["vraag"]})
    s["question"] = c["vraag"]
    s.update(agent._route(s))
    docs, best = set(), -1.0
    for m in s["modules"]:
        hits = retrieve(agent.store, s["q_emb"], s["concepts"] + s["related"][:2], None if m == ALGEMEEN else [m], cfg)
        docs |= {h["doc_id"] for h in hits}
        best = max([best] + [h["cosine"] for h in hits])
    conf = agent._confidence([{"cosine": best}] * 2) if best > -1 else "laag"
    if c["verwacht"]:
        n_rel += 1
        r_ok = c.get("module") in s["modules"]
        h_ok = all(d in docs for d in c["verwacht"])
        route_ok += r_ok
        hits_ok += h_ok
        cos_rel.append(best)
        mark = ("✓" if r_ok else "✗") + ("✓" if h_ok else "✗")
    else:
        cos_off.append(best)
        mark = "✓ " if conf == "laag" else "✗ "
    print(f"{mark} cos={best:.3f} {conf:<6} {str(s['modules']):<40} {c['vraag']}")

print(f"\nRoutering: {route_ok}/{n_rel}   hit@k (alle verwachte docs gevonden): {hits_ok}/{n_rel}")
if cos_rel and cos_off:
    print(f"Beste cosine relevant : min {min(cos_rel):.3f}  mediaan {statistics.median(cos_rel):.3f}")
    print(f"Beste cosine off-topic: max {max(cos_off):.3f}")
    print(f"Huidige drempels ({cfg['backends']['embedding']}): {thresholds(cfg)}")
    print("Tip: zet confidence_low tussen max(off-topic) en min(relevant).")
