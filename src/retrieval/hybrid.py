"""Hybrid retrieval: BM25 (SQLite FTS5) + dense vectors (Chroma), fused with
Reciprocal Rank Fusion, always filtered by team metadata first.

Why hybrid: meeting talk is full of exact tokens that matter ("twelve fifty",
"titanium", "kinetic") which BM25 nails, while paraphrased intent ("stop it
getting lost") needs dense similarity. RRF needs no score calibration.

`per_meeting` mode guarantees each of the team's meetings contributes its best
chunks, which is what multi-meeting / "how did it change" questions need.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import config
from src.memory import db

STOP = set("""a an the and or but if of to in on at for with by from as is are was were be been being do does did
have has had i you he she it we they them their our your my me us this that these those what which who whom whose
when where why how all any both each few more most other some such no nor not only own same so than too very can
will just should now team remote control final meeting meetings did they what who""".split())


@dataclass
class Hit:
    chunk_id: str
    meeting_id: str
    team_id: str
    meeting_order: int
    turn_start: int
    turn_end: int
    text: str
    score: float = 0.0
    sources: set = field(default_factory=set)   # {"bm25","vector","neighbor","memory"}
    queries: set = field(default_factory=set)


def fts_query(q: str) -> str:
    terms = [t for t in re.findall(r"[A-Za-z0-9']+", q.lower()) if t not in STOP and len(t) > 1]
    terms = [t.replace("'", "") for t in terms]
    return " OR ".join(f'"{t}"' for t in dict.fromkeys(terms)) or '""'


def bm25(conn, query: str, team_id: str | None, k: int, meeting_id: str | None = None) -> list[str]:
    sql = "SELECT chunk_id FROM chunks_fts WHERE chunks_fts MATCH ?"
    args: list = [fts_query(query)]
    if team_id:
        sql += " AND team_id = ?"
        args.append(team_id)
    if meeting_id:
        sql += " AND meeting_id = ?"
        args.append(meeting_id)
    sql += " ORDER BY bm25(chunks_fts) LIMIT ?"
    args.append(k)
    try:
        return [r[0] for r in conn.execute(sql, args)]
    except Exception:
        return []


class HybridRetriever:
    def __init__(self, conn=None, vstore=None):
        self.conn = conn or db.connect()
        if vstore is None:
            from src.retrieval.vector_store import VectorStore
            vstore = VectorStore()
        self.vstore = vstore

    def _hit(self, chunk_id) -> Hit | None:
        r = db.get_chunk(self.conn, chunk_id)
        if not r:
            return None
        return Hit(chunk_id=r["chunk_id"], meeting_id=r["meeting_id"], team_id=r["team_id"],
                   meeting_order=r["meeting_order"], turn_start=r["turn_start"], turn_end=r["turn_end"],
                   text=r["text"])

    def search(self, query: str, team_id: str | None = None, k: int = config.RETRIEVAL_TOP_K,
               per_meeting: int = 0, rrf_k: int = 60) -> list[Hit]:
        ranked_lists: list[tuple[str, list[str]]] = [
            ("bm25", bm25(self.conn, query, team_id, k * 2)),
            ("vector", [cid for cid, _ in self.vstore.query(query, k * 2, team_id)]),
        ]
        if per_meeting and team_id:
            for m in db.team_meetings(self.conn, team_id):
                ranked_lists.append(("bm25", bm25(self.conn, query, team_id, per_meeting, m["meeting_id"])))
        scores: dict[str, float] = {}
        srcs: dict[str, set] = {}
        for name, lst in ranked_lists:
            for rank, cid in enumerate(lst):
                scores[cid] = scores.get(cid, 0.0) + 1.0 / (rrf_k + rank + 1)
                srcs.setdefault(cid, set()).add(name)
        order = sorted(scores, key=lambda c: -scores[c])
        # keep global top-k plus anything that came from the per-meeting lists
        keep = order[:k]
        if per_meeting:
            for name, lst in ranked_lists[2:]:
                keep += [c for c in lst[:per_meeting] if c not in keep]
        hits = []
        for cid in keep:
            h = self._hit(cid)
            if h:
                h.score, h.sources, h.queries = scores[cid], srcs[cid], {query}
                hits.append(h)
        return hits

    def neighbors(self, hit: Hit) -> list[Hit]:
        """Adjacent chunks in the same meeting (context before/after a hit)."""
        n = int(hit.chunk_id.rsplit("-c", 1)[1])
        out = []
        for j in (n - 1, n + 1):
            if j >= 0:
                h = self._hit(f"{hit.meeting_id}-c{j:03d}")
                if h:
                    h.sources = {"neighbor"}
                    out.append(h)
        return out
