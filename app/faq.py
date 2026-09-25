"""Dynamische FAQ met exponentieel vervallende populariteit.

Idee: elke FAQ-vraag heeft een score die bij elke (vergelijkbare) vraag +1 krijgt en
daarna exponentieel vervalt met een halfwaardetijd (standaard 14 dagen):

    score(t) = score(t0) * 0.5 ** ((t - t0) / halfwaardetijd)

- Vaak en recent gesteld  -> hoge score, blijft bovenaan.
- Lang niet gesteld        -> score zakt langzaam onder 'min_score_visible' (verdwijnt uit beeld)
                              en uiteindelijk onder 'prune_below' (wordt verwijderd).
- Vergelijkbare vragen     -> samengevoegd op basis van embedding-similarity (geen dubbelingen).
- Kwaliteitspoort          -> alleen vragen met een voldoende betrouwbaar antwoord komen erin;
                              duimpje omhoog/omlaag stuurt bij.

We slaan per item alleen (score, tijdstip) op en rekenen verval 'lazy' uit: O(1) per update,
geen achtergrondjob nodig.
"""
from __future__ import annotations

import json
import math
import sqlite3
import time
from pathlib import Path

import numpy as np

CONF_RANK = {"laag": 0, "middel": 1, "hoog": 2}

SCHEMA = """
CREATE TABLE IF NOT EXISTS faq_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    vraag       TEXT NOT NULL,
    antwoord    TEXT NOT NULL,
    betrouwbaarheid TEXT NOT NULL,
    module      TEXT,
    bronnen     TEXT,           -- json lijst
    varianten   TEXT,           -- json lijst van andere formuleringen
    embedding   BLOB NOT NULL,
    score       REAL NOT NULL,  -- score op moment score_ts
    score_ts    REAL NOT NULL,
    n_gesteld   INTEGER NOT NULL DEFAULT 1,
    likes       INTEGER NOT NULL DEFAULT 0,
    dislikes    INTEGER NOT NULL DEFAULT 0,
    eerste_ts   REAL NOT NULL,
    laatste_ts  REAL NOT NULL
);
"""


class DynamicFAQ:
    def __init__(self, db_path: str | Path, half_life_days: float = 14, min_score_visible: float = 0.75,
                 prune_below: float = 0.2, max_items: int = 15, duplicate_threshold: float = 0.86,
                 min_confidence: str = "middel", min_question_chars: int = 12):
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.half_life_s = half_life_days * 86400
        self.min_visible, self.prune_below, self.max_items = min_score_visible, prune_below, max_items
        self.dup_threshold = duplicate_threshold
        self.min_conf, self.min_chars = min_confidence, min_question_chars

    @classmethod
    def from_config(cls, cfg: dict) -> "DynamicFAQ":
        from .config import resolve, thresholds

        f = cfg["faq"]
        return cls(resolve(f["db_path"]), f["half_life_days"], f["min_score_visible"], f["prune_below"],
                   f["max_items"], thresholds(cfg)["faq_duplicate"], f["min_confidence"], f["min_question_chars"])

    # ------------------------------------------------------------ kern
    def decayed(self, score: float, since: float, now: float) -> float:
        return score * 0.5 ** (max(0.0, now - since) / self.half_life_s)

    def _rows(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM faq_items").fetchall()

    def nearest(self, emb: np.ndarray) -> tuple[sqlite3.Row | None, float]:
        best, best_sim = None, -1.0
        e = np.asarray(emb, dtype=np.float32)
        for r in self._rows():
            sim = float(np.frombuffer(r["embedding"], dtype=np.float32) @ e)
            if sim > best_sim:
                best, best_sim = r, sim
        return best, best_sim

    def is_good_question(self, question: str, confidence: str) -> bool:
        q = question.strip()
        return len(q) >= self.min_chars and len(q.split()) >= 3 and CONF_RANK[confidence] >= CONF_RANK[self.min_conf]

    def record(self, question: str, emb: np.ndarray, answer: str, confidence: str, module: str | None = None,
               sources: list[str] | None = None, now: float | None = None, weight: float = 1.0) -> dict:
        """Registreer een gestelde vraag. Geeft {'actie': 'nieuw'|'bijgewerkt'|'genegeerd', 'id': ...}."""
        now = time.time() if now is None else now
        if not self.is_good_question(question, confidence):
            return {"actie": "genegeerd", "id": None, "reden": "kwaliteitspoort"}
        row, sim = self.nearest(emb)
        if row is not None and sim >= self.dup_threshold:
            new_score = self.decayed(row["score"], row["score_ts"], now) + weight
            variants = json.loads(row["varianten"] or "[]")
            if question.strip().lower() != row["vraag"].strip().lower() and question not in variants:
                variants = (variants + [question])[-5:]
            better = CONF_RANK[confidence] > CONF_RANK[row["betrouwbaarheid"]]
            self.conn.execute(
                """UPDATE faq_items SET score=?, score_ts=?, n_gesteld=n_gesteld+1, laatste_ts=?, varianten=?,
                   antwoord=CASE WHEN ? THEN ? ELSE antwoord END,
                   betrouwbaarheid=CASE WHEN ? THEN ? ELSE betrouwbaarheid END,
                   bronnen=CASE WHEN ? THEN ? ELSE bronnen END WHERE id=?""",
                (new_score, now, now, json.dumps(variants), better, answer, better, confidence,
                 better, json.dumps(sources or []), row["id"]),
            )
            self.conn.commit()
            return {"actie": "bijgewerkt", "id": row["id"], "similarity": sim}
        cur = self.conn.execute(
            """INSERT INTO faq_items (vraag, antwoord, betrouwbaarheid, module, bronnen, varianten, embedding,
               score, score_ts, eerste_ts, laatste_ts) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (question.strip(), answer, confidence, module, json.dumps(sources or []), "[]",
             np.asarray(emb, dtype=np.float32).tobytes(), weight, now, now, now),
        )
        self.conn.commit()
        return {"actie": "nieuw", "id": cur.lastrowid}

    def feedback(self, item_id: int, positive: bool, now: float | None = None) -> None:
        """Duim omhoog = +0.5 score; duim omlaag = -1. Veel negatieve feedback -> verwijderen."""
        now = time.time() if now is None else now
        r = self.conn.execute("SELECT * FROM faq_items WHERE id=?", (item_id,)).fetchone()
        if r is None:
            return
        score = max(0.0, self.decayed(r["score"], r["score_ts"], now) + (0.5 if positive else -1.0))
        likes, dislikes = r["likes"] + positive, r["dislikes"] + (not positive)
        if dislikes >= 3 and dislikes > likes:
            self.conn.execute("DELETE FROM faq_items WHERE id=?", (item_id,))
        else:
            self.conn.execute("UPDATE faq_items SET score=?, score_ts=?, likes=?, dislikes=? WHERE id=?",
                              (score, now, likes, dislikes, item_id))
        self.conn.commit()

    def prune(self, now: float | None = None) -> int:
        now = time.time() if now is None else now
        dead = [r["id"] for r in self._rows() if self.decayed(r["score"], r["score_ts"], now) < self.prune_below]
        self.conn.executemany("DELETE FROM faq_items WHERE id=?", [(i,) for i in dead])
        self.conn.commit()
        return len(dead)

    def top(self, now: float | None = None, include_hidden: bool = False) -> list[dict]:
        now = time.time() if now is None else now
        self.prune(now)
        items = []
        for r in self._rows():
            s = self.decayed(r["score"], r["score_ts"], now)
            if include_hidden or s >= self.min_visible:
                items.append({
                    "id": r["id"], "vraag": r["vraag"], "antwoord": r["antwoord"], "score": round(s, 3),
                    "betrouwbaarheid": r["betrouwbaarheid"], "module": r["module"],
                    "bronnen": json.loads(r["bronnen"] or "[]"), "varianten": json.loads(r["varianten"] or "[]"),
                    "n_gesteld": r["n_gesteld"], "likes": r["likes"], "dislikes": r["dislikes"],
                    "dagen_geleden": round((now - r["laatste_ts"]) / 86400, 1),
                    "zichtbaar": s >= self.min_visible,
                })
        items.sort(key=lambda x: -x["score"])
        return items if include_hidden else items[: self.max_items]

    def clear(self) -> None:
        self.conn.execute("DELETE FROM faq_items")
        self.conn.commit()

    def days_until_hidden(self, score: float) -> float:
        """Hoeveel dagen zonder nieuwe vragen voordat een item uit de FAQ verdwijnt."""
        if score <= self.min_visible:
            return 0.0
        return self.half_life_s / 86400 * math.log2(score / self.min_visible)
