import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents import ExpertAgent  # noqa: E402
from app.config import load_config  # noqa: E402
from app.faq import DynamicFAQ  # noqa: E402
from app.graph_store import MemoryStore  # noqa: E402
from app.ingest import ingest  # noqa: E402
from app.llm import FakeChat, HashEmbedder  # noqa: E402

DEMO = {"backends": {"store": "memory", "embedding": "hash", "llm": "fake"}}


@pytest.fixture(scope="session")
def cfg():
    return load_config(overrides=DEMO)


@pytest.fixture(scope="session")
def store(cfg):
    s = MemoryStore()
    ingest(cfg, s, HashEmbedder(), log=lambda *_: None)
    return s


@pytest.fixture()
def agent(cfg, store):
    faq = DynamicFAQ(":memory:", duplicate_threshold=cfg["thresholds"]["hash"]["faq_duplicate"])
    return ExpertAgent(cfg, store, HashEmbedder(), FakeChat(), faq)
