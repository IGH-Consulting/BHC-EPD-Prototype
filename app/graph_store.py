"""Kennisgraaf-opslag.

Graph-schema (Neo4j):

  (:Bron {naam})                       'standaard' | 'ziekenhuis'
  (:Document {id, titel, type, versie, organisatie, pad})-[:UIT_BRON]->(:Bron)
  (:Document)-[:OVER_MODULE]->(:Module {naam, beschrijving})-[:BEHEERD_DOOR]->(:Werkgroep {naam})
  (:Document)-[:VERFIJNT]->(:Document)   werkinstructie/opleiding verfijnt standaarddoc
  (:Chunk {id, tekst, sectie, volgorde, embedding})-[:DEEL_VAN]->(:Document)
  (:Chunk)-[:VOLGT_OP]->(:Chunk)
  (:Chunk)-[:NOEMT]->(:Concept {naam})-[:HOORT_BIJ]->(:Module)
  (:Concept)-[:GERELATEERD_AAN {gewicht}]-(:Concept)   co-occurrence in chunks

Twee implementaties met dezelfde interface:
  Neo4jStore  – voor het echte prototype (Docker)
  MemoryStore – in-process, voor tests en demo zonder Docker
"""
from __future__ import annotations

import pickle
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np

Hit = dict[str, Any]


class GraphStore:
    def reset(self) -> None: ...
    def ensure_schema(self, dim: int) -> None: ...
    def upsert_domain(self, modules: dict, concepts: dict) -> None: ...
    def add_document(self, doc: dict, chunks: list[dict]) -> None: ...
    def finalize(self) -> None: ...
    def vector_search(self, emb: np.ndarray, k: int, modules: list[str] | None) -> list[Hit]: ...
    def chunks_for_concepts(self, concepts: list[str], modules: list[str] | None, limit: int) -> list[Hit]: ...
    def refined_chunks(self, doc_ids: list[str], limit: int) -> list[Hit]: ...
    def related_concepts(self, concepts: list[str], limit: int) -> list[str]: ...
    def stats(self) -> dict[str, int]: ...
    def close(self) -> None: ...


# ======================================================================
# Neo4j
# ======================================================================
_HIT_RETURN = """
  RETURN c.id AS chunk_id, c.tekst AS tekst, c.sectie AS sectie, c.embedding AS embedding,
         d.id AS doc_id, d.titel AS titel, d.type AS type, d.versie AS versie,
         b.naam AS bron, m.naam AS module,
         [(c)-[:NOEMT]->(x:Concept) | x.naam] AS concepten
"""
_HIT_MATCH = "MATCH (c)-[:DEEL_VAN]->(d:Document)-[:UIT_BRON]->(b:Bron), (d)-[:OVER_MODULE]->(m:Module)"


class Neo4jStore(GraphStore):
    def __init__(self, uri: str, user: str, password: str, database: str = "neo4j"):
        from neo4j import GraphDatabase

        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self.db = database
        self.driver.verify_connectivity()

    def _run(self, q: str, **params) -> list[dict]:
        with self.driver.session(database=self.db) as s:
            return [r.data() for r in s.run(q, **params)]

    def reset(self) -> None:
        self._run("MATCH (n) DETACH DELETE n")
        self._run("DROP INDEX chunk_embedding IF EXISTS")

    def ensure_schema(self, dim: int) -> None:
        for label, prop in [("Document", "id"), ("Chunk", "id"), ("Module", "naam"),
                            ("Werkgroep", "naam"), ("Concept", "naam"), ("Bron", "naam")]:
            self._run(f"CREATE CONSTRAINT {label.lower()}_{prop} IF NOT EXISTS "
                      f"FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE")
        # Index-opties zijn niet parametriseerbaar; dim is een int uit de embedder.
        self._run(
            "CREATE VECTOR INDEX chunk_embedding IF NOT EXISTS FOR (c:Chunk) ON (c.embedding) "
            f"OPTIONS {{indexConfig: {{`vector.dimensions`: {int(dim)}, `vector.similarity_function`: 'cosine'}}}}"
        )
        self._run("CALL db.awaitIndexes(300)")

    def upsert_domain(self, modules: dict, concepts: dict) -> None:
        self._run(
            """UNWIND $mods AS m
               MERGE (mod:Module {naam: m.naam}) SET mod.beschrijving = m.beschrijving
               MERGE (w:Werkgroep {naam: m.werkgroep})
               MERGE (mod)-[:BEHEERD_DOOR]->(w)""",
            mods=[{"naam": k, **v} for k, v in modules.items()],
        )
        self._run(
            """UNWIND $cons AS c
               MERGE (con:Concept {naam: c.naam})
               WITH con, c MATCH (m:Module {naam: c.module}) MERGE (con)-[:HOORT_BIJ]->(m)""",
            cons=[{"naam": k, "module": v["module"]} for k, v in concepts.items()],
        )

    def add_document(self, doc: dict, chunks: list[dict]) -> None:
        self._run(
            """MERGE (b:Bron {naam: $doc.bron})
               MERGE (d:Document {id: $doc.id})
               SET d.titel = $doc.titel, d.type = $doc.type, d.versie = $doc.versie,
                   d.organisatie = $doc.organisatie, d.pad = $doc.pad, d.verfijnt = $doc.verfijnt
               MERGE (d)-[:UIT_BRON]->(b)
               MERGE (m:Module {naam: $doc.module})
               MERGE (d)-[:OVER_MODULE]->(m)""",
            doc=doc,
        )
        self._run(
            """MATCH (d:Document {id: $doc_id})
               UNWIND $chunks AS ch
               MERGE (c:Chunk {id: ch.id})
               SET c.tekst = ch.tekst, c.sectie = ch.sectie, c.volgorde = ch.volgorde, c.embedding = ch.embedding
               MERGE (c)-[:DEEL_VAN]->(d)
               WITH c, ch
               UNWIND ch.concepten AS naam
               MERGE (x:Concept {naam: naam})
               MERGE (c)-[:NOEMT]->(x)""",
            doc_id=doc["id"],
            chunks=[{**c, "embedding": [float(v) for v in c["embedding"]]} for c in chunks],
        )
        self._run(
            """UNWIND range(0, size($ids) - 2) AS i
               MATCH (a:Chunk {id: $ids[i]}), (b:Chunk {id: $ids[i + 1]})
               MERGE (a)-[:VOLGT_OP]->(b)""",
            ids=[c["id"] for c in chunks],
        )

    def finalize(self) -> None:
        # VERFIJNT-relaties (na ingestie van alle documenten)
        self._run(
            """MATCH (d:Document) WHERE d.verfijnt IS NOT NULL
               UNWIND d.verfijnt AS target
               MATCH (t:Document {id: target}) MERGE (d)-[:VERFIJNT]->(t)"""
        )
        # Concept co-occurrence
        self._run("MATCH ()-[r:GERELATEERD_AAN]-() DELETE r")
        self._run(
            """MATCH (a:Concept)<-[:NOEMT]-(c:Chunk)-[:NOEMT]->(b:Concept)
               WHERE a.naam < b.naam
               WITH a, b, count(c) AS n
               MERGE (a)-[r:GERELATEERD_AAN]->(b) SET r.gewicht = n"""
        )

    def vector_search(self, emb: np.ndarray, k: int, modules: list[str] | None) -> list[Hit]:
        rows = self._run(
            f"""CALL db.index.vector.queryNodes('chunk_embedding', $k, $emb) YIELD node AS c, score
                {_HIT_MATCH}
                WHERE $modules IS NULL OR m.naam IN $modules
                {_HIT_RETURN}, score""",
            k=k, emb=[float(x) for x in emb], modules=modules,
        )
        for r in rows:  # Neo4j normaliseert cosine naar (1 + cos) / 2
            r["score"] = 2 * r["score"] - 1
        return rows

    def chunks_for_concepts(self, concepts: list[str], modules: list[str] | None, limit: int) -> list[Hit]:
        if not concepts:
            return []
        return self._run(
            f"""MATCH (c:Chunk)-[:NOEMT]->(x:Concept) WHERE x.naam IN $concepts
                WITH c, count(x) AS n ORDER BY n DESC LIMIT $limit
                {_HIT_MATCH}
                WHERE $modules IS NULL OR m.naam IN $modules
                {_HIT_RETURN}""",
            concepts=concepts, modules=modules, limit=limit,
        )

    def refined_chunks(self, doc_ids: list[str], limit: int) -> list[Hit]:
        if not doc_ids:
            return []
        return self._run(
            f"""MATCH (src:Document)-[:VERFIJNT]-(d2:Document) WHERE src.id IN $ids AND NOT d2.id IN $ids
                MATCH (c:Chunk)-[:DEEL_VAN]->(d2)
                WITH DISTINCT c LIMIT $limit
                {_HIT_MATCH}
                {_HIT_RETURN}""",
            ids=doc_ids, limit=limit,
        )

    def related_concepts(self, concepts: list[str], limit: int) -> list[str]:
        if not concepts:
            return []
        rows = self._run(
            """MATCH (a:Concept)-[r:GERELATEERD_AAN]-(b:Concept)
               WHERE a.naam IN $c AND NOT b.naam IN $c
               RETURN b.naam AS naam, sum(r.gewicht) AS w ORDER BY w DESC LIMIT $limit""",
            c=concepts, limit=limit,
        )
        return [r["naam"] for r in rows]

    def stats(self) -> dict[str, int]:
        rows = self._run("MATCH (n) RETURN labels(n)[0] AS label, count(*) AS n")
        out = {r["label"]: r["n"] for r in rows}
        out["relaties"] = self._run("MATCH ()-[r]->() RETURN count(r) AS n")[0]["n"]
        return out

    def close(self) -> None:
        self.driver.close()


# ======================================================================
# In-memory (zelfde semantiek, voor tests/demo zonder Docker)
# ======================================================================
class MemoryStore(GraphStore):
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self._empty()
        if self.path and self.path.exists():
            with open(self.path, "rb") as f:
                self.__dict__.update(pickle.load(f))

    def _empty(self) -> None:
        self.modules: dict[str, dict] = {}
        self.concepts: dict[str, str] = {}            # concept -> module
        self.docs: dict[str, dict] = {}
        self.chunks: dict[str, dict] = {}
        self.order: list[str] = []                     # rij-volgorde van self.matrix
        self.matrix = np.zeros((0, 0), dtype=np.float32)
        self.refines: set[tuple[str, str]] = set()     # (doc, target)
        self.cooc: dict[tuple[str, str], int] = {}

    def _save(self) -> None:
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "wb") as f:
                pickle.dump({k: v for k, v in self.__dict__.items() if k != "path"}, f)

    def reset(self) -> None:
        self._empty()

    def ensure_schema(self, dim: int) -> None:
        self.matrix = np.zeros((0, dim), dtype=np.float32)

    def upsert_domain(self, modules: dict, concepts: dict) -> None:
        self.modules.update(modules)
        self.concepts.update({k: v["module"] for k, v in concepts.items()})

    def add_document(self, doc: dict, chunks: list[dict]) -> None:
        self.docs[doc["id"]] = doc
        new = []
        for c in chunks:
            self.chunks[c["id"]] = {k: v for k, v in c.items() if k != "embedding"} | {"doc_id": doc["id"]}
            self.order.append(c["id"])
            new.append(np.asarray(c["embedding"], dtype=np.float32))
        if new:
            self.matrix = np.vstack([self.matrix, np.stack(new)]) if self.matrix.size else np.stack(new)

    def finalize(self) -> None:
        self.refines = {(d["id"], t) for d in self.docs.values() for t in (d.get("verfijnt") or []) if t in self.docs}
        cooc: dict[tuple[str, str], int] = defaultdict(int)
        for c in self.chunks.values():
            for a, b in combinations(sorted(set(c["concepten"])), 2):
                cooc[(a, b)] += 1
        self.cooc = dict(cooc)
        self._save()

    def _hit(self, cid: str, score: float | None = None) -> Hit:
        c, d = self.chunks[cid], self.docs[self.chunks[cid]["doc_id"]]
        return {
            "chunk_id": cid, "tekst": c["tekst"], "sectie": c["sectie"],
            "embedding": self.matrix[self.order.index(cid)],
            "doc_id": d["id"], "titel": d["titel"], "type": d["type"], "versie": d["versie"],
            "bron": d["bron"], "module": d["module"], "concepten": c["concepten"], "score": score,
        }

    def _in(self, cid: str, modules: list[str] | None) -> bool:
        return modules is None or self.docs[self.chunks[cid]["doc_id"]]["module"] in modules

    def vector_search(self, emb: np.ndarray, k: int, modules: list[str] | None) -> list[Hit]:
        if not self.order:
            return []
        sims = self.matrix @ np.asarray(emb, dtype=np.float32)
        idx = np.argsort(-sims)[:k]  # zelfde gedrag als Neo4j: eerst top-k, dan filteren
        return [self._hit(self.order[i], float(sims[i])) for i in idx if self._in(self.order[i], modules)]

    def chunks_for_concepts(self, concepts: list[str], modules: list[str] | None, limit: int) -> list[Hit]:
        cs = set(concepts)
        scored = [(len(cs & set(c["concepten"])), cid) for cid, c in self.chunks.items()]
        scored = sorted([s for s in scored if s[0] > 0], key=lambda s: -s[0])[:limit]
        return [self._hit(cid) for _, cid in scored if self._in(cid, modules)]

    def refined_chunks(self, doc_ids: list[str], limit: int) -> list[Hit]:
        ids = set(doc_ids)
        linked = {b for a, b in self.refines if a in ids} | {a for a, b in self.refines if b in ids}
        linked -= ids
        return [self._hit(cid) for cid, c in self.chunks.items() if c["doc_id"] in linked][:limit]

    def related_concepts(self, concepts: list[str], limit: int) -> list[str]:
        cs, w = set(concepts), defaultdict(int)
        for (a, b), n in self.cooc.items():
            if a in cs and b not in cs:
                w[b] += n
            elif b in cs and a not in cs:
                w[a] += n
        return [k for k, _ in sorted(w.items(), key=lambda kv: -kv[1])[:limit]]

    def stats(self) -> dict[str, int]:
        return {
            "Document": len(self.docs), "Chunk": len(self.chunks), "Module": len(self.modules),
            "Werkgroep": len({m["werkgroep"] for m in self.modules.values()}),
            "Concept": len(self.concepts), "Bron": len({d["bron"] for d in self.docs.values()}),
            "VERFIJNT": len(self.refines), "GERELATEERD_AAN": len(self.cooc),
        }

    def close(self) -> None:
        pass


def make_store(cfg: dict) -> GraphStore:
    from .config import resolve

    if cfg["backends"]["store"] == "memory":
        return MemoryStore(resolve(cfg["memory_store"]["path"]))
    n = cfg["neo4j"]
    return Neo4jStore(n["uri"], n["user"], n["password"], n["database"])
