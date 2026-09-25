import yaml

from app.config import ROOT


def test_routing_and_hits_on_golden_set(agent, cfg):
    cases = yaml.safe_load(open(ROOT / "data" / "eval_vragen.yaml", encoding="utf-8"))
    for c in [c for c in cases if c["verwacht"]]:
        r = agent.ask(c["vraag"], use_faq=False, record_faq=False)
        assert c["module"] in r["modules"], c["vraag"]
        docs = {s["titel"] for s in r["sources"]}
        assert r["sources"] and r["confidence"] in {"hoog", "middel"}, c["vraag"]
        assert docs


def test_local_knowledge_is_used(agent):
    r = agent.ask("Voor welke middelen is een dubbele controle verplicht?", use_faq=False, record_faq=False)
    assert r["sources"][0]["bron"] == "ziekenhuis"
    assert "insuline" in r["answer"].lower() or any("insuline" in s["tekst"].lower() for s in r["sources"][:2])


def test_multi_agent_fan_out_and_unique_source_numbers(agent):
    r = agent.ask("Opname kan niet worden afgesloten door openstaande orders", use_faq=False, record_faq=False)
    assert len(r["agents"]) == 2
    nrs = [s["nr"] for s in r["sources"]]
    assert len(nrs) == len(set(nrs))


def test_off_topic_escalates(agent):
    r = agent.ask("Waar kan ik mijn parkeerkaart ophalen?", use_faq=False, record_faq=False)
    assert r["confidence"] == "laag" and r["escalate"]


def test_faq_is_filled_and_shortcut_used(agent):
    q = "Wat betekent de melding barcode niet herkend bij toedienen?"
    first = agent.ask(q)
    assert first["faq"]["actie"] == "nieuw"
    second = agent.ask(q)
    assert second["from_faq"]
    assert agent.faq.top()[0]["n_gesteld"] == 2
