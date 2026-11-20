"""Local embeddings + vector index.

Embeddings: sentence-transformers/all-MiniLM-L6-v2 (384-d, runs on CPU, free).
Index: ChromaDB persistent collection with team_id / meeting_id metadata so that
queries can be filtered to a team before similarity search. If chromadb is not
importable (e.g. no wheel for the interpreter) we fall back to an exact NumPy
index persisted as .npy — identical interface, fine up to ~100k chunks.
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

import numpy as np

import config

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _model():
    from sentence_transformers import SentenceTransformer
    try:  # use the local cache without a network round-trip when available
        return SentenceTransformer(config.EMBEDDING_MODEL, device="cpu", local_files_only=True)
    except Exception:
        return SentenceTransformer(config.EMBEDDING_MODEL, device="cpu")


def embed(texts: list[str], batch_size: int = config.EMBED_BATCH_SIZE) -> np.ndarray:
    return _model().encode(texts, batch_size=batch_size, normalize_embeddings=True,
                           show_progress_bar=False, convert_to_numpy=True)


class VectorStore:
    """Interface: upsert(ids, texts, metadatas), delete_meeting(mid), query(text, k, team_id)."""

    def __init__(self, path: Path = config.CHROMA_DIR):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        try:
            import chromadb
            self._client = chromadb.PersistentClient(path=str(self.path))
            self._col = self._client.get_or_create_collection("chunks", metadata={"hnsw:space": "cosine"})
            self.backend = "chromadb"
        except Exception as e:  # pragma: no cover - environment dependent
            log.warning("chromadb unavailable (%s); using NumPy exact index", e)
            self.backend = "numpy"
            self._npy, self._meta = self.path / "vectors.npy", self.path / "meta.json"
            self._vecs = np.load(self._npy) if self._npy.exists() else np.zeros((0, 384), dtype=np.float32)
            self._metas = json.loads(self._meta.read_text()) if self._meta.exists() else []

    # ---------------- write ----------------
    def upsert(self, ids: list[str], texts: list[str], metadatas: list[dict]):
        for s in range(0, len(ids), 512):
            e = s + 512
            vecs = embed(texts[s:e])
            if self.backend == "chromadb":
                self._col.upsert(ids=ids[s:e], embeddings=vecs.tolist(), metadatas=metadatas[s:e])
            else:
                keep = [i for i, m in enumerate(self._metas) if m["id"] not in set(ids[s:e])]
                self._vecs = np.vstack([self._vecs[keep], vecs.astype(np.float32)])
                self._metas = [self._metas[i] for i in keep] + [{"id": i, **m} for i, m in zip(ids[s:e], metadatas[s:e])]
        if self.backend == "numpy":
            self._save()

    def delete_meeting(self, meeting_id: str):
        if self.backend == "chromadb":
            self._col.delete(where={"meeting_id": meeting_id})
        else:
            keep = [i for i, m in enumerate(self._metas) if m["meeting_id"] != meeting_id]
            self._vecs, self._metas = self._vecs[keep], [self._metas[i] for i in keep]
            self._save()

    def _save(self):
        np.save(self._npy, self._vecs)
        self._meta.write_text(json.dumps(self._metas), encoding="utf-8")

    def ids(self) -> list[str]:
        if self.backend == "chromadb":
            return self._col.get(include=[])["ids"]
        return [m["id"] for m in self._metas]

    def count(self) -> int:
        return self._col.count() if self.backend == "chromadb" else len(self._metas)

    # ---------------- read ----------------
    def query(self, text: str, k: int = 10, team_id: str | None = None) -> list[tuple[str, float]]:
        """Returns [(chunk_id, cosine_similarity)] best first."""
        q = embed([text])[0]
        if self.backend == "chromadb":
            res = self._col.query(query_embeddings=[q.tolist()], n_results=k,
                                  where={"team_id": team_id} if team_id else None)
            return [(i, 1.0 - d) for i, d in zip(res["ids"][0], res["distances"][0])]
        idx = [i for i, m in enumerate(self._metas) if not team_id or m["team_id"] == team_id]
        if not idx:
            return []
        sims = self._vecs[idx] @ q
        order = np.argsort(-sims)[:k]
        return [(self._metas[idx[o]]["id"], float(sims[o])) for o in order]
