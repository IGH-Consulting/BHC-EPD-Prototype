"""Model-clients: Ollama (lokaal, gratis) plus offline fallbacks voor demo en tests.

- OllamaChat / OllamaEmbedder  -> echte lokale modellen via http://localhost:11434
- HashEmbedder                 -> lexicale n-gram embedding, geen model nodig
- FakeChat                     -> extractief 'antwoord' uit de context, geen model nodig
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Protocol

import numpy as np
import requests


class Chat(Protocol):
    def chat(self, system: str, user: str, json_mode: bool = False) -> str: ...


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> np.ndarray: ...


# ---------------------------------------------------------------- Ollama
class OllamaChat:
    def __init__(self, url: str, model: str, temperature: float = 0.1, num_ctx: int = 4096, timeout_s: int = 300):
        self.url, self.model = url.rstrip("/"), model
        self.options = {"temperature": temperature, "num_ctx": num_ctx}
        self.timeout = timeout_s

    def chat(self, system: str, user: str, json_mode: bool = False) -> str:
        payload = {
            "model": self.model,
            "stream": False,
            "options": self.options,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        if json_mode:
            payload["format"] = "json"
        r = requests.post(f"{self.url}/api/chat", json=payload, timeout=self.timeout)
        r.raise_for_status()
        return r.json()["message"]["content"].strip()


class OllamaEmbedder:
    def __init__(self, url: str, model: str, timeout_s: int = 300, batch: int = 16):
        self.url, self.model, self.timeout, self.batch = url.rstrip("/"), model, timeout_s, batch

    def embed(self, texts: list[str]) -> np.ndarray:
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch):
            r = requests.post(
                f"{self.url}/api/embed",
                json={"model": self.model, "input": texts[i : i + self.batch]},
                timeout=self.timeout,
            )
            r.raise_for_status()
            out.extend(r.json()["embeddings"])
        return _normalize(np.asarray(out, dtype=np.float32))


# ---------------------------------------------------------------- Offline fallbacks
_WORD = re.compile(r"[a-zà-ÿ0-9]+", re.IGNORECASE)
_STOP = set(
    "de het een en of in op van voor met is zijn wordt worden bij als dan dat die dit niet naar door "
    "aan te om uit je ik we hoe wat wie waar kan kun moet mag ook nog er over tot na al".split()
)


class HashEmbedder:
    """Woorden + karakter-trigrammen gehasht naar een vaste vector (TF, log-geschaald).

    Geen semantiek, wel robuust voor woordvarianten ('toediening' ~ 'toedienen').
    Alleen bedoeld voor demo zonder Ollama en voor tests.
    """

    def __init__(self, dim: int = 1024):
        self.dim = dim

    def _features(self, text: str) -> list[str]:
        words = [w.lower() for w in _WORD.findall(text) if w.lower() not in _STOP]
        feats = [f"w:{w}" for w in words]
        for w in words:
            p = f"#{w}#"
            feats += [f"g:{p[i:i+3]}" for i in range(len(p) - 2)]
        return feats

    def embed(self, texts: list[str]) -> np.ndarray:
        m = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, t in enumerate(texts):
            for f in self._features(t):
                h = int.from_bytes(hashlib.md5(f.encode()).digest()[:4], "little")
                weight = 1.0 if f.startswith("w:") else 0.3
                m[row, h % self.dim] += weight
        m = np.log1p(m)
        return _normalize(m)


class FakeChat:
    """Demo-'LLM': geeft de meest relevante zinnen uit de aangeleverde context terug.

    Houdt het prototype bruikbaar zonder model en maakt tests deterministisch.
    """

    def chat(self, system: str, user: str, json_mode: bool = False) -> str:
        if json_mode:
            return json.dumps({"concepten": []})
        question = user.split("VRAAG:", 1)[-1].split("\n", 1)[0] if "VRAAG:" in user else user[:200]
        context = user.split("CONTEXT:", 1)[-1] if "CONTEXT:" in user else user
        # Kopjes en separators (### [1] ..., ---) geen zinnen maken.
        lines = [ln for ln in context.splitlines() if ln.strip() and not ln.lstrip().startswith(("###", "---", ">", "#"))]
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", " ".join(lines)) if len(s.strip()) > 25]
        q = {w.lower() for w in _WORD.findall(question) if w.lower() not in _STOP and len(w) > 2}

        def score(s: str) -> float:
            ws = {w.lower() for w in _WORD.findall(s)}
            overlap = sum(1 for w in q if any(x.startswith(w[:6]) for x in ws))
            return overlap / math.sqrt(len(ws) + 1)

        best = sorted(sentences, key=score, reverse=True)[:4]
        if not best:
            return "Ik kan op basis van de beschikbare kennis geen antwoord geven."
        body = "\n".join(f"- {s}" for s in best)
        return f"(demo-modus, extractief antwoord)\n{body}"


# ---------------------------------------------------------------- factory
def _normalize(m: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(m, axis=1, keepdims=True)
    n[n == 0] = 1.0
    return m / n


def make_chat(cfg: dict) -> Chat:
    if cfg["backends"]["llm"] == "fake":
        return FakeChat()
    o = cfg["ollama"]
    return OllamaChat(o["url"], o["chat_model"], o["temperature"], o["num_ctx"], o["timeout_s"])


def make_embedder(cfg: dict) -> Embedder:
    if cfg["backends"]["embedding"] == "hash":
        return HashEmbedder()
    o = cfg["ollama"]
    return OllamaEmbedder(o["url"], o["embed_model"], o["timeout_s"])
