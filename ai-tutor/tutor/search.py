import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .embed import embed_query

RRF_K = 60
CANDIDATES = 50

_vector_cache: dict[str, tuple[tuple, np.ndarray, np.ndarray]] = {}


@dataclass
class Hit:
    chunk_id: int
    file_id: int
    file: str
    page_no: int
    text: str
    score: float


def _vectors(conn: sqlite3.Connection, course: str) -> tuple[np.ndarray, np.ndarray]:
    stamp = tuple(conn.execute(
        "SELECT COUNT(*), MAX(c.id) FROM chunks c JOIN files f ON f.id = c.file_id WHERE f.course = ?", (course,)
    ).fetchone())
    cached = _vector_cache.get(course)
    if cached and cached[0] == stamp:
        return cached[1], cached[2]
    rows = conn.execute(
        "SELECT c.id, c.embedding FROM chunks c JOIN files f ON f.id = c.file_id WHERE f.course = ?", (course,)
    ).fetchall()
    ids = np.array([r[0] for r in rows], dtype=np.int64)
    mat = np.frombuffer(b"".join(r[1] for r in rows), dtype=np.float32).reshape(len(rows), -1) if rows else np.zeros((0, 1))
    _vector_cache[course] = (stamp, ids, mat)
    return ids, mat


def _vector_ranks(conn, course: str, query: str) -> list[int]:
    ids, mat = _vectors(conn, course)
    if not len(ids):
        return []
    sims = mat @ embed_query(query)
    top = np.argsort(-sims)[:CANDIDATES]
    return [int(ids[i]) for i in top]


def _keyword_ranks(conn, course: str, query: str) -> list[int]:
    terms = re.findall(r"\w+", query.lower())
    if not terms:
        return []
    match = " OR ".join(f'"{t}"' for t in terms)
    rows = conn.execute(
        """SELECT c.id FROM chunks_fts
           JOIN chunks c ON c.id = chunks_fts.rowid
           JOIN files f ON f.id = c.file_id
           WHERE chunks_fts MATCH ? AND f.course = ?
           ORDER BY bm25(chunks_fts) LIMIT ?""",
        (match, course, CANDIDATES),
    ).fetchall()
    return [r[0] for r in rows]


def hybrid_search(conn: sqlite3.Connection, course: str, query: str, k: int = 6) -> list[Hit]:
    """Keyword (BM25) + vector (cosine) retrieval merged with reciprocal rank fusion."""
    scores: dict[int, float] = {}
    for ranking in (_keyword_ranks(conn, course, query), _vector_ranks(conn, course, query)):
        for rank, chunk_id in enumerate(ranking):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank + 1)
    best = sorted(scores, key=scores.get, reverse=True)[:k]
    if not best:
        return []
    rows = conn.execute(
        f"""SELECT c.id, c.file_id, c.page_no, c.text, f.path FROM chunks c JOIN files f ON f.id = c.file_id
            WHERE c.id IN ({",".join("?" * len(best))})""",
        best,
    ).fetchall()
    by_id = {r["id"]: r for r in rows}
    return [
        Hit(i, by_id[i]["file_id"], Path(by_id[i]["path"]).name, by_id[i]["page_no"], by_id[i]["text"], scores[i])
        for i in best
    ]


def find_phrase(conn: sqlite3.Connection, course: str, phrase: str, limit: int = 15) -> list[tuple[str, int]]:
    """Exact (case-insensitive) phrase lookup, e.g. '2.2 Exercises' or 'variation of parameters'."""
    pattern = "%" + re.sub(r"\s+", "%", phrase.strip()) + "%"
    rows = conn.execute(
        """SELECT f.path, p.page_no FROM pages p JOIN files f ON f.id = p.file_id
           WHERE f.course = ? AND (p.text LIKE ? OR p.ocr_text LIKE ?)
           ORDER BY f.path, p.page_no LIMIT ?""",
        (course, pattern, pattern, limit),
    ).fetchall()
    return [(Path(r["path"]).name, r["page_no"]) for r in rows]
