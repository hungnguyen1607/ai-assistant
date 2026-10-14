import json
import re
import sqlite3

import pymupdf

from .config import DATA_DIR, FAST_MODEL, MODEL, course_dir
from .llm import client

VERSION = 4

PROMPT = """Below is a course outline. Extract the week-by-week schedule as JSON:
{"term_start": "2026-09-08",
 "weeks": [{"week": "1", "topics": "Propositional Logic", "sections": "1.1, 1.2, 1.3", "note": "",
            "problems": {"1.1": "1, 3, 5", "1.2": "7, 9"}}],
 "exams": [{"name": "Midterm", "date": "2026-10-25", "covers": "weeks 1-6"}]}
- "term_start" is the first day of classes if the outline states it, else "".
- "week" is a label like "1" or "7"; keep the outline's order and wording. Include breaks such as reading
  week in their place as {"week": "break", "topics": "Reading week", "sections": "", "note": ""}.
- "sections" are textbook sections exactly as listed ("" if none).
- "assignment" is the assignment number tied to that week if the schedule has such a column, else "".
- "problems" maps each section to its suggested/assigned exercise numbers if the outline lists them, else {}.
- "note" is for things like "Midterm Test (October 25)"; "" otherwise.
- "exams" lists every test/exam with date (YYYY-MM-DD if given) and what it covers if stated.
Return only the JSON.

OUTLINE:
"""


def find_outline(conn: sqlite3.Connection, course: str):
    """The outline is the course-folder PDF with 'outline' or 'syllabus' in its name."""
    root = course_dir(course)
    for r in conn.execute("SELECT id, path, sha256 FROM files WHERE course = ? ORDER BY path", (course,)):
        name = r["path"].rsplit("/", 1)[-1].lower()
        if ("outline" in name or "syllabus" in name) and r["path"].startswith(str(root)):
            return r
    return None


def textbook_sections(conn: sqlite3.Connection, course: str) -> dict[str, dict]:
    """Section number → title and PDF page range, from the textbook PDF's bookmarks."""
    out: dict[str, dict] = {}
    textbook = str(course_dir(course) / "textbook")
    for r in conn.execute("SELECT path, pages FROM files WHERE course = ? ORDER BY pages DESC", (course,)):
        if not r["path"].startswith(textbook):
            continue
        try:
            toc = pymupdf.open(r["path"]).get_toc()
        except Exception:
            continue
        for i, (_, title, page) in enumerate(toc):
            m = re.match(r"(\d+\.\d+)\s+(.+)", title.strip())
            if not m or m.group(1) in out:
                continue
            end = next((p for _, _, p in toc[i + 1:] if p > page), r["pages"] + 1) - 1
            out[m.group(1)] = {"section": m.group(1), "title": m.group(2), "page": page, "end_page": max(page, end),
                               "file": r["path"].rsplit("/", 1)[-1]}
        if out:
            break
    return out


def with_sections(conn: sqlite3.Connection, course: str, data: dict) -> dict:
    toc = textbook_sections(conn, course)
    for w in data["weeks"]:
        nums = list(dict.fromkeys(re.findall(r"\d+\.\d+", w.get("sections", ""))))
        probs = w.get("problems") or {}
        w["parts"] = [
            {**toc.get(n, {"section": n, "title": "", "page": 0, "end_page": 0, "file": ""}),
             "problems": str(probs.get(n, ""))}
            for n in nums
        ]
    return _borrow_breaks(course, data)


def _borrow_breaks(course: str, data: dict) -> dict:
    """Same term, same reading week: if this outline lists no break, copy the position from another course's."""
    if not data["weeks"] or any(w["week"] == "break" for w in data["weeks"]):
        return data
    for f in DATA_DIR.glob("outline-*.json"):
        if f.stem == f"outline-{course}":
            continue
        other = json.loads(f.read_text()).get("weeks", [])
        idx = next((i for i, w in enumerate(other) if w.get("week") == "break"), None)
        if idx is not None and idx <= len(data["weeks"]):
            brk = {**other[idx], "parts": [], "note": f"not in this outline; from {f.stem.removeprefix('outline-').upper()}'s"}
            data["weeks"] = data["weeks"][:idx] + [brk] + data["weeks"][idx:]
            break
    return data


def get(conn: sqlite3.Connection, course: str, refresh: bool = False) -> dict:
    return with_sections(conn, course, _get(conn, course, refresh))


def _get(conn: sqlite3.Connection, course: str, refresh: bool = False) -> dict:
    f = find_outline(conn, course)
    if not f:
        return {"weeks": [], "exams": [], "missing": True}
    cache = DATA_DIR / f"outline-{course}.json"
    if cache.exists() and not refresh:
        data = json.loads(cache.read_text())
        if data.get("sha256") == f["sha256"] and data.get("version") == VERSION:
            return data
    text = "\n".join(
        r["ocr_text"] or r["text"]
        for r in conn.execute("SELECT text, ocr_text FROM pages WHERE file_id = ? ORDER BY page_no", (f["id"],))
    )
    data = None
    for model in (FAST_MODEL, MODEL):
        try:
            resp = client().chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": PROMPT + text[:30000]}],
                response_format={"type": "json_object"},
            )
            raw = resp.choices[0].message.content or ""
            data = json.loads(re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.M))
            break
        except Exception:
            continue
    if data is None:
        raise RuntimeError("couldn't read the outline")
    data = {"weeks": data.get("weeks", []), "exams": data.get("exams", []),
            "term_start": data.get("term_start", ""), "version": VERSION, "sha256": f["sha256"],
            "file": f["path"].rsplit("/", 1)[-1]}
    cache.write_text(json.dumps(data, indent=1))
    return data
