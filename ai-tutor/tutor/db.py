import sqlite3

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY,
    course TEXT NOT NULL,
    path TEXT NOT NULL UNIQUE,
    sha256 TEXT NOT NULL,
    pages INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS pages (
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    page_no INTEGER NOT NULL,          -- 1-based, as shown in a PDF viewer
    text TEXT NOT NULL,                -- raw text layer from the PDF
    ocr_text TEXT,                     -- vision-model transcription (math as LaTeX), filled lazily
    PRIMARY KEY (file_id, page_no)
);
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    page_no INTEGER NOT NULL,
    text TEXT NOT NULL,
    embedding BLOB NOT NULL            -- float32, L2-normalized
);
CREATE INDEX IF NOT EXISTS chunks_page ON chunks(file_id, page_no);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(text, tokenize='porter unicode61');
CREATE TABLE IF NOT EXISTS problems (
    id INTEGER PRIMARY KEY,
    course TEXT NOT NULL,
    chapter TEXT NOT NULL,
    section TEXT NOT NULL,            -- e.g. '2.2'
    number TEXT NOT NULL,             -- e.g. '6' or '6a'
    title TEXT NOT NULL,              -- short label shown in lists
    statement TEXT NOT NULL,          -- full problem text (Markdown + LaTeX)
    solution TEXT NOT NULL,           -- worked steps + check (Markdown)
    answer TEXT NOT NULL DEFAULT '',
    verified INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT '',  -- e.g. 'textbook/Zill.pdf p.179'
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE (course, section, number)
);
"""


def connect() -> sqlite3.Connection:
    # the web server streams each reply from a worker thread; one connection is used by one request at a time
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)
    return conn


def delete_chunks(conn: sqlite3.Connection, file_id: int, page_no: int | None = None) -> None:
    where, args = ("file_id = ?", (file_id,)) if page_no is None else ("file_id = ? AND page_no = ?", (file_id, page_no))
    ids = [r[0] for r in conn.execute(f"SELECT id FROM chunks WHERE {where}", args)]
    conn.executemany("DELETE FROM chunks_fts WHERE rowid = ?", [(i,) for i in ids])
    conn.execute(f"DELETE FROM chunks WHERE {where}", args)
