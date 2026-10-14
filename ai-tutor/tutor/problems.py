"""Solved-problem library: one row per problem, browsable in the web app."""

import re
import sqlite3
from pathlib import Path

from .config import solutions_dir

FIELDS = "id, course, chapter, section, number, title, statement, solution, answer, verified, source, created_at, updated_at"


def _num_key(text: str) -> tuple:
    return tuple(int(n) if n.isdigit() else n for n in re.findall(r"\d+|[a-zA-Z]+", text))


def _row(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["verified"] = bool(d["verified"])
    return d


def save(conn: sqlite3.Connection, course: str, *, section: str, number: str, title: str, statement: str,
         solution: str, answer: str = "", verified: bool = False, source: str = "", chapter: str = "") -> tuple[int, bool]:
    """Insert or update a problem. Returns (id, created)."""
    section, number = section.strip(), str(number).strip().lstrip("#")
    chapter = (chapter or section.split(".")[0]).removeprefix("chapter-").strip()
    existing = conn.execute(
        "SELECT id FROM problems WHERE course = ? AND section = ? AND number = ?", (course, section, number)
    ).fetchone()
    values = (chapter, title.strip(), statement.strip(), solution.strip(), answer.strip(), int(bool(verified)), source.strip())
    if existing:
        conn.execute(
            """UPDATE problems SET chapter = ?, title = ?, statement = ?, solution = ?, answer = ?, verified = ?,
               source = ?, updated_at = datetime('now', 'localtime') WHERE id = ?""",
            (*values, existing["id"]),
        )
        conn.commit()
        return existing["id"], False
    cur = conn.execute(
        """INSERT INTO problems (course, section, number, chapter, title, statement, solution, answer, verified, source)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (course, section, number, *values),
    )
    conn.commit()
    return cur.lastrowid, True


def list_all(conn: sqlite3.Connection, course: str) -> list[dict]:
    rows = conn.execute(
        "SELECT id, chapter, section, number, title, answer, verified FROM problems WHERE course = ?", (course,)
    ).fetchall()
    return sorted((dict(r) | {"verified": bool(r["verified"])} for r in rows),
                  key=lambda p: (_num_key(p["chapter"]), _num_key(p["section"]), _num_key(p["number"])))


def get(conn: sqlite3.Connection, problem_id: int) -> dict | None:
    r = conn.execute(f"SELECT {FIELDS} FROM problems WHERE id = ?", (problem_id,)).fetchone()
    return _row(r) if r else None


def find(conn: sqlite3.Connection, course: str, section: str, number: str) -> dict | None:
    r = conn.execute(
        f"SELECT {FIELDS} FROM problems WHERE course = ? AND section = ? AND number = ?",
        (course, section.strip(), str(number).strip().lstrip("#")),
    ).fetchone()
    return _row(r) if r else None


def delete(conn: sqlite3.Connection, problem_id: int) -> bool:
    cur = conn.execute("DELETE FROM problems WHERE id = ?", (problem_id,))
    conn.commit()
    return cur.rowcount > 0


def to_markdown(p: dict) -> str:
    parts = [f"## Problem {p['number']} — {p['title']}"]
    if p["statement"] and p["statement"] != p["title"]:
        parts.append(p["statement"])
    parts.append(p["solution"])
    if p["answer"] and "**Answer" not in p["solution"]:
        parts.append(f"**Answer: {p['answer']}**")
    if p["source"]:
        parts.append(f"_Source: {p['source']}_")
    return "\n\n".join(parts)


PROBLEM_RE = re.compile(r"^## Problem (\S+) — (.+)$", re.M)
ANSWER_RE = re.compile(r"\*\*Answer:\s*(.+?)\*\*")


def import_markdown(conn: sqlite3.Connection, course: str, log=print) -> int:
    """Load existing <course>/solutions/chapter-N/<section>-solutions.md files into the library."""
    added = 0
    root = solutions_dir(course)
    for path in sorted(root.rglob("*-solutions.md")) if root.is_dir() else []:
        m = re.match(r"(\d+(?:\.\d+)*)-solutions\.md$", path.name)
        if not m:
            continue
        section, text = m.group(1), path.read_text()
        heads = list(PROBLEM_RE.finditer(text))
        for i, head in enumerate(heads):
            end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
            body = text[head.end():end]
            body = re.split(r"^#{1,3} (?!Problem)", body, flags=re.M)[0]  # drop trailing pattern/notes sections
            body = re.sub(r"(\s*---\s*)+\Z", "", body.strip())
            number, title = head.group(1), head.group(2).strip()
            if find(conn, course, section, number):
                continue
            answer = ANSWER_RE.search(body)
            save(conn, course, section=section, number=number, title=title, statement=title, solution=body,
                 answer=answer.group(1).strip() if answer else "", verified="SymPy: verified" in body,
                 source=str(Path(path).relative_to(root)), chapter=path.parent.name)
            added += 1
        log(f"{path.relative_to(root)}: {len(heads)} problems")
    return added
