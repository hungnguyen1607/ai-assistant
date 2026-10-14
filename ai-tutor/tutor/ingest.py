import hashlib
import re
import sqlite3
from pathlib import Path

import pymupdf

from .config import CHUNK_CHARS, CHUNK_OVERLAP, SOLUTIONS_SUBDIR, course_dir
from .db import connect, delete_chunks
from .embed import embed

TEXT_SUFFIXES = {".md", ".txt"}


def chunk_text(text: str) -> list[str]:
    text = re.sub(r"[ \t]+", " ", text).strip()
    if len(text) < 20:
        return []
    chunks, start = [], 0
    while start < len(text):
        end = min(start + CHUNK_CHARS, len(text))
        if end < len(text):
            # prefer to cut at a paragraph or sentence boundary in the last third of the window
            cut = max(text.rfind("\n\n", start, end), text.rfind(". ", start, end))
            if cut > start + CHUNK_CHARS * 2 // 3:
                end = cut + 1
        chunks.append(text[start:end].strip())
        if end == len(text):
            break
        start = end - CHUNK_OVERLAP
    return chunks


def index_page(conn: sqlite3.Connection, file_id: int, page_no: int, text: str) -> int:
    delete_chunks(conn, file_id, page_no)
    pieces = chunk_text(text)
    if not pieces:
        return 0
    for piece, vec in zip(pieces, embed(pieces)):
        cur = conn.execute(
            "INSERT INTO chunks (file_id, page_no, text, embedding) VALUES (?, ?, ?, ?)",
            (file_id, page_no, piece, vec.tobytes()),
        )
        conn.execute("INSERT INTO chunks_fts (rowid, text) VALUES (?, ?)", (cur.lastrowid, piece))
    return len(pieces)


def _read_pages(path: Path) -> list[str]:
    if path.suffix.lower() in TEXT_SUFFIXES:
        return [path.read_text(errors="ignore")]
    with pymupdf.open(path) as doc:
        return [page.get_text() for page in doc]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def ingest_course(course: str, log=print) -> None:
    course = course.lower()
    root = course_dir(course)
    if not root.is_dir():
        raise SystemExit(f"No folder {root}. Put the course PDFs there first.")
    files = sorted(
        p for p in root.rglob("*")
        if p.suffix.lower() in TEXT_SUFFIXES | {".pdf"} and not p.is_relative_to(root / SOLUTIONS_SUBDIR)
    )
    conn = connect()
    seen_hashes: dict[str, Path] = {}
    for path in files:
        sha = _sha256(path)
        if sha in seen_hashes:
            log(f"skip  {path.name} (duplicate of {seen_hashes[sha].name})")
            continue
        seen_hashes[sha] = path
        row = conn.execute("SELECT id, sha256 FROM files WHERE path = ?", (str(path),)).fetchone()
        if not row:
            moved = next(
                (r for r in conn.execute("SELECT id, path FROM files WHERE course = ? AND sha256 = ?", (course, sha))
                 if not Path(r["path"]).exists()),
                None,
            )
            if moved:
                conn.execute("UPDATE files SET path = ? WHERE id = ?", (str(path), moved["id"]))
                log(f"moved {Path(moved['path']).name} → {path.relative_to(root)}")
                continue
        if row and row["sha256"] == sha:
            log(f"ok    {path.name} (unchanged)")
            continue
        if row:
            conn.execute("DELETE FROM files WHERE id = ?", (row["id"],))
            delete_chunks(conn, row["id"])

        texts = _read_pages(path)
        file_id = conn.execute(
            "INSERT INTO files (course, path, sha256, pages) VALUES (?, ?, ?, ?)",
            (course, str(path), sha, len(texts)),
        ).lastrowid
        is_text_file = path.suffix.lower() in TEXT_SUFFIXES
        n_chunks = 0
        for i, text in enumerate(texts, start=1):
            conn.execute(
                "INSERT INTO pages (file_id, page_no, text, ocr_text) VALUES (?, ?, ?, ?)",
                (file_id, i, text, text if is_text_file else None),
            )
            n_chunks += index_page(conn, file_id, i, text)
            if i % 200 == 0:
                conn.commit()
                log(f"      {path.name}: {i}/{len(texts)} pages")
        conn.commit()
        log(f"added {path.name}: {len(texts)} pages, {n_chunks} chunks")

    # drop files that were deleted from the folder
    for row in conn.execute("SELECT id, path FROM files WHERE course = ?", (course,)).fetchall():
        if not Path(row["path"]).exists():
            delete_chunks(conn, row["id"])
            conn.execute("DELETE FROM files WHERE id = ?", (row["id"],))
            log(f"removed {Path(row['path']).name}")
    conn.commit()
