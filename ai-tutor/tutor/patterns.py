"""Problem patterns per course (LeetCode-style): how to spot a problem type, its template, variations and traps."""

import json
import re
import sqlite3

from . import outline
from .config import FAST_MODEL, MODEL, solutions_dir
from .llm import client


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "pattern"


def list_all(conn: sqlite3.Connection, course: str) -> list[dict]:
    rows = conn.execute(
        """SELECT p.id, p.slug, p.name, p.sections, p.recognize, p.body != '' AS filled,
                  COUNT(q.id) AS solved, SUM(q.verified) AS verified
           FROM patterns p LEFT JOIN problems q ON q.pattern_id = p.id
           WHERE p.course = ? GROUP BY p.id""",
        (course,),
    ).fetchall()
    out = [dict(r) | {"filled": bool(r["filled"]), "verified": r["verified"] or 0} for r in rows]
    return sorted(out, key=lambda p: (_section_key(p["sections"]), p["name"]))


def _section_key(sections: str) -> tuple:
    m = re.search(r"(\d+)\.(\d+)", sections or "")
    return (int(m.group(1)), int(m.group(2))) if m else (999, 0)


def find(conn: sqlite3.Connection, course: str, name_or_slug: str) -> dict | None:
    slug = slugify(name_or_slug)
    r = conn.execute("SELECT * FROM patterns WHERE course = ? AND (slug = ? OR lower(name) = lower(?))",
                     (course, slug, name_or_slug.strip())).fetchone()
    return dict(r) if r else None


def problems_for(conn: sqlite3.Connection, pattern_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT id, section, number, title, answer, verified FROM problems WHERE pattern_id = ? ORDER BY section, number",
        (pattern_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def upsert(conn: sqlite3.Connection, course: str, name: str, *, sections: str = "", recognize: str = "",
           body: str | None = None) -> dict:
    existing = find(conn, course, name)
    if existing:
        conn.execute(
            """UPDATE patterns SET sections = COALESCE(NULLIF(?, ''), sections),
                   recognize = COALESCE(NULLIF(?, ''), recognize), body = COALESCE(?, body),
                   updated_at = datetime('now', 'localtime') WHERE id = ?""",
            (sections.strip(), recognize.strip(), body.strip() if body is not None else None, existing["id"]),
        )
        pid = existing["id"]
    else:
        pid = conn.execute(
            "INSERT INTO patterns (course, slug, name, sections, recognize, body) VALUES (?, ?, ?, ?, ?, ?)",
            (course, slugify(name), name.strip(), sections.strip(), recognize.strip(), (body or "").strip()),
        ).lastrowid
    conn.commit()
    p = dict(conn.execute("SELECT * FROM patterns WHERE id = ?", (pid,)).fetchone())
    write_file(conn, course, p)
    return p


def tag(conn: sqlite3.Connection, problem_id: int, pattern_id: int | None) -> None:
    conn.execute("UPDATE problems SET pattern_id = ? WHERE id = ?", (pattern_id, problem_id))
    conn.commit()


def to_markdown(conn: sqlite3.Connection, p: dict) -> str:
    parts = [f"# {p['name']}"]
    if p["sections"]:
        parts.append(f"_Sections: {p['sections']}_")
    if p["recognize"]:
        parts.append(f"**Spot it:** {p['recognize']}")
    parts.append(p["body"] or "_Not filled in yet. Click \"Fill in this pattern\" or solve a problem of this type._")
    probs = problems_for(conn, p["id"])
    lines = [f"- {q['section']} #{q['number']} — {q['title']}" + (" ✓" if q["verified"] else "") for q in probs]
    parts.append(f"## Problems solved ({len(probs)})\n\n" + ("\n".join(lines) or "_None yet._"))
    return "\n\n".join(parts)


def write_file(conn: sqlite3.Connection, course: str, p: dict) -> None:
    folder = solutions_dir(course) / "patterns"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{p['slug']}.md").write_text(to_markdown(conn, p) + "\n")


def refresh_file(conn: sqlite3.Connection, course: str, pattern_id: int | None) -> None:
    if pattern_id:
        r = conn.execute("SELECT * FROM patterns WHERE id = ?", (pattern_id,)).fetchone()
        if r:
            write_file(conn, course, dict(r))


def _ask_json(prompt: str) -> dict:
    last = None
    for model in (FAST_MODEL, MODEL):
        try:
            resp = client().chat.completions.create(
                model=model, messages=[{"role": "user", "content": prompt}], response_format={"type": "json_object"}
            )
            raw = (resp.choices[0].message.content or "").strip()
            return json.loads(re.sub(r"^```(json)?|```$", "", raw, flags=re.M))
        except Exception as e:
            last = e
    raise RuntimeError(f"pattern model call failed: {last}")


SEED_PROMPT = """You're building a LeetCode-style pattern list for a university course, so a student can see every
problem type they need to master. Below are the course's textbook sections in schedule order.

List the distinct problem patterns (solution methods / question types) a student must recognize, as JSON:
{{"patterns": [{{"name": "Separable equations", "sections": "2.2", "recognize": "dy/dx factors as g(x)·h(y)"}}]}}
- One pattern per distinct method or question type an exam would ask; split a section into several if it
  has clearly different problem types, merge across sections when it's the same method.
- "recognize" is one short line: the tell in the question that says "use this".
- Aim for 2-4 patterns per section. Keep names short.

COURSE: {course}
SECTIONS:
{sections}
"""

TAG_PROMPT = """Assign each solved problem to the pattern it mainly uses. Patterns (slug: name — tell):
{patterns}

Problems:
{problems}

Return JSON {{"tags": {{"<problem id>": "<slug>"}}}}. Use only the slugs above; omit a problem if nothing fits.
"""


def seed(conn: sqlite3.Connection, course: str) -> dict:
    data = outline.get(conn, course)
    parts = [p for w in data.get("weeks", []) for p in w.get("parts", [])]
    if not parts:
        toc = outline.textbook_sections(conn, course)
        if not toc:
            raise RuntimeError("no outline sections or textbook table of contents to build patterns from")
        parts = list(toc.values())[:40]
    seen, lines = set(), []
    for p in parts:
        if p["section"] not in seen:
            seen.add(p["section"])
            lines.append(f"{p['section']} {p.get('title', '')}".strip())
    out = _ask_json(SEED_PROMPT.format(course=course.upper(), sections="\n".join(lines)))
    added = 0
    for item in out.get("patterns", []):
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        if not find(conn, course, name):
            added += 1
        upsert(conn, course, name, sections=str(item.get("sections", "")), recognize=str(item.get("recognize", "")))
    return {"added": added, "tagged": tag_untagged(conn, course)}


def tag_untagged(conn: sqlite3.Connection, course: str) -> int:
    pats = list_all(conn, course)
    probs = conn.execute(
        "SELECT id, section, number, title, statement FROM problems WHERE course = ? AND pattern_id IS NULL", (course,)
    ).fetchall()
    if not pats or not probs:
        return 0
    out = _ask_json(TAG_PROMPT.format(
        patterns="\n".join(f"{p['slug']}: {p['name']} — {p['recognize']}" for p in pats),
        problems="\n".join(f"{q['id']}: {q['section']} #{q['number']} {q['title']} — {q['statement'][:300]}" for q in probs),
    ))
    by_slug = {p["slug"]: p["id"] for p in pats}
    tagged = 0
    for pid, slug in (out.get("tags") or {}).items():
        if str(pid).isdigit() and slug in by_slug:
            tag(conn, int(pid), by_slug[slug])
            tagged += 1
    for p in pats:
        refresh_file(conn, course, p["id"])
    return tagged
