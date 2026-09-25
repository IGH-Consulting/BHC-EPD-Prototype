import numpy as np
import pytest

from app.faq import DynamicFAQ

DAY = 86400.0


def vec(i, dim=8):
    v = np.zeros(dim, dtype=np.float32)
    v[i] = 1
    return v


@pytest.fixture()
def faq():
    return DynamicFAQ(":memory:", half_life_days=14, min_score_visible=0.75, prune_below=0.2,
                      duplicate_threshold=0.9, min_confidence="middel")


def test_half_life(faq):
    assert faq.decayed(4.0, 0, 14 * DAY) == pytest.approx(2.0)
    assert faq.decayed(4.0, 0, 28 * DAY) == pytest.approx(1.0)


def test_similar_questions_merge_and_accumulate(faq):
    faq.record("Hoe registreer ik niet toegediend?", vec(0), "a", "hoog", now=0)
    r = faq.record("Hoe leg ik niet toegediend vast?", vec(0), "a", "hoog", now=0)
    assert r["actie"] == "bijgewerkt"
    [item] = faq.top(now=0)
    assert item["n_gesteld"] == 2 and item["score"] == pytest.approx(2.0)
    assert item["varianten"] == ["Hoe leg ik niet toegediend vast?"]


def test_recent_popular_beats_old_popular(faq):
    for d in [40, 41, 42, 43, 44]:                        # oud maar vaak
        faq.record("Oude populaire vraag over opname?", vec(1), "a", "hoog", now=-d * DAY)
    for d in [1, 2]:                                      # recent, minder vaak
        faq.record("Recente vraag over barcodes?", vec(2), "a", "hoog", now=-d * DAY)
    ranking = [it["vraag"] for it in faq.top(now=0, include_hidden=True)]
    assert ranking[0].startswith("Recente")


def test_items_fade_out_then_get_pruned(faq):
    faq.record("Vraag die niemand meer stelt?", vec(3), "a", "hoog", now=0)
    assert faq.top(now=5 * DAY)                            # 1 * 0.5^(5/14) = 0.78 -> zichtbaar
    assert not faq.top(now=7 * DAY)                        # 0.71 -> weggezakt
    assert faq.top(now=7 * DAY, include_hidden=True)       # ...maar nog aanwezig
    faq.top(now=40 * DAY)                                  # 0.14 -> verwijderd
    assert not faq.top(now=40 * DAY, include_hidden=True)


def test_quality_gate(faq):
    assert faq.record("kort?", vec(4), "a", "hoog", now=0)["actie"] == "genegeerd"
    assert faq.record("Een prima lange vraag hier?", vec(4), "a", "laag", now=0)["actie"] == "genegeerd"


def test_better_answer_replaces_worse(faq):
    faq.record("Hoe werkt de dubbele controle precies?", vec(5), "matig antwoord", "middel", now=0)
    faq.record("Hoe werkt de dubbele controle precies?", vec(5), "goed antwoord", "hoog", now=0)
    assert faq.top(now=0)[0]["antwoord"] == "goed antwoord"


def test_negative_feedback_removes(faq):
    faq.record("Een vraag met een slecht antwoord?", vec(6), "a", "hoog", now=0)
    item_id = faq.top(now=0)[0]["id"]
    for _ in range(3):
        faq.feedback(item_id, positive=False, now=0)
    assert not faq.top(now=0, include_hidden=True)


def test_days_until_hidden(faq):
    assert faq.days_until_hidden(1.5) == pytest.approx(14.0)
