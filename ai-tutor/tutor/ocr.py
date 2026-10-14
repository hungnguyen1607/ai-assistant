import base64
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pymupdf

from .config import FAST_MODEL
from .ingest import index_page
from .llm import client

OCR_PROMPT = (
    "Transcribe this page to Markdown exactly. Write every formula in LaTeX ($...$ inline, $$...$$ display). "
    "Always put exponents in braces and look carefully at what is raised: e^{x}y (only x in the exponent) is "
    "different from e^{xy}. Keep section titles, problem numbers, figure captions and tables. Describe figures "
    "in one line as [Figure: ...]. Output only the transcription."
)
DPI = 220


def _transcribe(path: str, page_no: int) -> str:
    with pymupdf.open(path) as doc:
        png = doc[page_no - 1].get_pixmap(dpi=DPI).tobytes("png")
    resp = client().chat.completions.create(
        model=FAST_MODEL,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": OCR_PROMPT},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}},
            ],
        }],
    )
    return (resp.choices[0].message.content or "").strip()


def ocr_pages(conn: sqlite3.Connection, file_id: int, page_nos: list[int]) -> dict[int, str]:
    """Return a vision transcription for each page, transcribing (in parallel) only uncached pages."""
    path = conn.execute("SELECT path FROM files WHERE id = ?", (file_id,)).fetchone()["path"]
    marks = ",".join("?" * len(page_nos))
    rows = conn.execute(
        f"SELECT page_no, ocr_text FROM pages WHERE file_id = ? AND page_no IN ({marks})", (file_id, *page_nos)
    ).fetchall()
    result = {r["page_no"]: r["ocr_text"] for r in rows if r["ocr_text"]}
    todo = [p for p in page_nos if p not in result and any(r["page_no"] == p for r in rows)]
    if todo:
        with ThreadPoolExecutor(max_workers=6) as pool:
            for page_no, text in zip(todo, pool.map(lambda p: _transcribe(path, p), todo)):
                conn.execute("UPDATE pages SET ocr_text = ? WHERE file_id = ? AND page_no = ?", (text, file_id, page_no))
                index_page(conn, file_id, page_no, text)  # search now sees the real math too
                result[page_no] = text
        conn.commit()
    return result
