"""Laadt config.yaml en maakt paden relatief aan de projectroot."""
from __future__ import annotations

import copy
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str | os.PathLike | None = None, overrides: dict | None = None) -> dict[str, Any]:
    cfg_path = Path(path or os.environ.get("EPD_CONFIG", ROOT / "config.yaml"))
    with open(cfg_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    # Omgevingsvariabelen overschrijven backends (handig voor demo/tests).
    for key in ("store", "llm", "embedding"):
        env = os.environ.get(f"EPD_{key.upper()}")
        if env:
            cfg["backends"][key] = env
    if os.environ.get("NEO4J_PASSWORD"):
        cfg["neo4j"]["password"] = os.environ["NEO4J_PASSWORD"]
    if os.environ.get("OLLAMA_URL"):
        cfg["ollama"]["url"] = os.environ["OLLAMA_URL"]
    if overrides:
        cfg = _deep_merge(cfg, overrides)
    return cfg


def resolve(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else ROOT / p


def thresholds(cfg: dict) -> dict[str, float]:
    return cfg["thresholds"][cfg["backends"]["embedding"]]


@lru_cache(maxsize=1)
def default_config() -> dict[str, Any]:
    return load_config()
