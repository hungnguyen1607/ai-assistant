import json
import re
import sqlite3
from pathlib import Path

from . import mathcheck, patterns, problems, profile
from .config import course_dir, solutions_dir
from .ocr import ocr_pages
from .runcode import run_code
from .search import find_phrase, hybrid_search

MAX_READ_PAGES = 6


def _fn(name: str, description: str, props: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": props, "required": required},
    }}


S = {"type": "string"}
I = {"type": "integer"}

SCHEMAS = [
    _fn("list_materials", "List the course's files (slides, outline, textbook) with page counts.", {}, []),
    _fn("search_materials",
        "Hybrid keyword + semantic search over the course materials. Returns snippets with file and page. "
        "Snippets of math-heavy pages may be missing equations; use read_pages to see the real math.",
        {"query": S, "k": {**I, "description": "number of results, default 6"}}, ["query"]),
    _fn("find_in_materials",
        "Exact phrase lookup returning (file, page) pairs, e.g. '2.2 Exercises', 'Variation of Parameters'.",
        {"phrase": S}, ["phrase"]),
    _fn("read_pages",
        f"Read up to {MAX_READ_PAGES} consecutive PDF pages, transcribed with math in LaTeX. Page numbers are "
        "PDF page numbers (as returned by search), not the printed page numbers.",
        {"file": {**S, "description": "file name or a unique part of it"}, "start_page": I, "end_page": I},
        ["file", "start_page"]),
    _fn("check_ode_solution",
        "Verify with SymPy that a solution satisfies an ODE. Notation: y', y'', dy/dx, e^(3x), ln, sin, sqrt. "
        "dx/dy and ln|y| are fine. Convert differential form M dx + N dy = 0 to dy/dx = -M/N first. Solution may "
        "be explicit 'y = C*x^4' or implicit 'x^2 + y^2 = C' (implicit ones are checked by comparing slopes, which "
        "works reliably). Pass the ORIGINAL equation from the book, not your rearranged one. NOT VERIFIED means "
        "the math is wrong somewhere: recheck integrals and constants; don't assume the checker is at fault.",
        {"ode": S, "solution": S, "func": {**S, "description": "dependent variable, default y"},
         "var": {**S, "description": "independent variable, default x"}}, ["ode", "solution"]),
    _fn("solve_ode", "Solve an ODE with SymPy (optionally with initial conditions like \"y(0)=1, y'(0)=2\").",
        {"ode": S, "ics": S, "func": S, "var": S}, ["ode"]),
    _fn("math",
        "SymPy calculator. op: simplify | factor | expand | partial_fractions | integrate | diff | solve | "
        "limit | equal | numeric. 'other': integrate bounds 'a,b'; diff order; limit point; the second "
        "expression for 'equal'.",
        {"op": S, "expr": S, "var": {**S, "description": "default x"}, "other": S}, ["op", "expr"]),
    _fn("run_code", "Run code (python, ruby, javascript, java) and return stdout/stderr. Java class must be Main.",
        {"language": S, "code": S, "stdin": S}, ["language", "code"]),
    _fn("list_solution_files", "List existing solution .md files for this course, by chapter folder.", {}, []),
    _fn("read_solution_file", "Read an existing solution file.", {"filename": S}, ["filename"]),
    _fn("write_solution_file",
        "Write solutions to <course>/solutions/chapter-N/<filename>.md. The chapter comes from the section number "
        "in the filename (2.5-solutions.md → chapter-2) unless 'chapter' is given. If a file with that name already "
        "exists in any chapter folder, it is reused. mode 'append' adds to the end, 'overwrite' replaces.",
        {"filename": {**S, "description": "e.g. 2.5-solutions.md"}, "content": S,
         "chapter": {**S, "description": "optional chapter number, e.g. '2'; needed when the filename has no section number. "
                                       "Use 'cheatsheets' for cheat sheets."},
         "mode": {"type": "string", "enum": ["append", "overwrite"]}}, ["filename", "content"]),
    _fn("save_problem",
        "Save ONE solved problem to the problem library (the web app's Library tab). Call once per problem. "
        "New problems are also appended to <section>-solutions.md in the right chapter folder, so don't also "
        "call write_solution_file for them. Re-saving the same section+number updates it.",
        {"section": {**S, "description": "e.g. '2.2'"},
         "number": {**S, "description": "problem number, e.g. '6'"},
         "title": {**S, "description": "short label, e.g. the equation in plain Unicode: 'dy/dx + 2xy² = 0'"},
         "statement": {**S, "description": "full problem text exactly as in the source; LaTeX math allowed"},
         "solution": {**S, "description": "worked steps + Check, in the solution-file format (Unicode math in a code "
                                         "block). Don't include the final Answer line; pass it as 'answer'."},
         "answer": {**S, "description": "final answer in plain Unicode"},
         "verified": {"type": "boolean", "description": "true only if SymPy/run_code confirmed the answer"},
         "source": {**S, "description": "where the problem came from, e.g. 'textbook/Zill.pdf p.179'"},
         "chapter": {**S, "description": "only if it can't be read from the section number"},
         "pattern": {**S, "description": "slug or name of the pattern this problem mainly uses (see list_patterns); "
                                         "a new name creates the pattern"}},
        ["section", "number", "title", "statement", "solution", "answer", "verified", "pattern"]),
    _fn("list_patterns",
        "List this course's problem patterns: slug, name, sections, how to spot it, problems solved, and whether "
        "its page is filled in.", {}, []),
    _fn("get_pattern", "Read a pattern's full page and the problems tagged with it.", {"pattern": S}, ["pattern"]),
    _fn("save_pattern",
        "Create or fill in a pattern page. body is Markdown with these parts: ## Template (numbered fill-in steps), "
        "## Variations (each: how it's twisted on tests, how to spot it, what changes, likelihood High/Medium/Low "
        "with the evidence), ## Traps, ## Most likely on the exam. Plain Unicode math in code blocks.",
        {"name": {**S, "description": "existing slug/name to update, or a new name"},
         "sections": {**S, "description": "textbook sections, e.g. '2.2'"},
         "recognize": {**S, "description": "one line: the tell in a question that says use this"},
         "body": S}, ["name", "body"]),
    _fn("get_saved_problem", "Look up a problem already in the library (to avoid re-solving it).",
        {"section": S, "number": S}, ["section", "number"]),
    _fn("update_profile",
        "Remember something about the learner. fields: known_terms, weak_spots, feedback (lists), style (text).",
        {"field": S, "value": S, "action": {"type": "string", "enum": ["add", "remove", "set"]}},
        ["field", "value"]),
]


class Toolbox:
    def __init__(self, conn: sqlite3.Connection, course: str):
        self.conn, self.course = conn, course
        self.solutions = solutions_dir(course)

    def call(self, name: str, raw_args: str) -> str:
        try:
            args = json.loads(raw_args or "{}")
            return str(getattr(self, "t_" + name)(**args))
        except Exception as exc:
            return f"ERROR: {type(exc).__name__}: {exc}"

    def _file(self, name: str) -> sqlite3.Row:
        rows = self.conn.execute(
            "SELECT id, path, pages FROM files WHERE course = ? AND path LIKE ?", (self.course, f"%{name}%")
        ).fetchall()
        if not rows:
            raise ValueError(f"no file matching '{name}'; call list_materials")
        if len(rows) > 1:
            raise ValueError("ambiguous file name, matches: " + ", ".join(Path(r["path"]).name for r in rows))
        return rows[0]

    def _solution_path(self, filename: str, chapter: str | None = None) -> Path:
        name = Path(filename).name
        if not re.fullmatch(r"[\w.\- ]+", name):
            raise ValueError("bad filename")
        name = name if name.endswith(".md") else name + ".md"
        existing = sorted(self.solutions.rglob(name)) if self.solutions.is_dir() else []
        if existing:
            return existing[0]
        chapter = str(chapter or "").strip().removeprefix("chapter-").removeprefix("chapter") or None
        if not chapter:
            m = re.match(r"(\d+)\.", name)
            if not m:
                raise ValueError("can't tell the chapter from the filename; pass chapter='N'")
            chapter = m.group(1)
        if not re.fullmatch(r"\w+", chapter):
            raise ValueError("bad chapter")
        if chapter in ("cheatsheets", "assignments"):
            return self.solutions / chapter / name
        return self.solutions / f"chapter-{chapter}" / name

    def t_list_materials(self):
        rows = self.conn.execute("SELECT path, pages FROM files WHERE course = ? ORDER BY path", (self.course,))
        root = course_dir(self.course)
        return "\n".join(
            f"{Path(r['path']).relative_to(root)} ({r['pages']} pages)" for r in rows
        ) or "no materials ingested"

    def t_search_materials(self, query, k=6):
        hits = hybrid_search(self.conn, self.course, query, int(k))
        return "\n\n".join(f"[{h.file} p.{h.page_no}]\n{h.text[:700]}" for h in hits) or "no results"

    def t_find_in_materials(self, phrase):
        hits = find_phrase(self.conn, self.course, phrase)
        return "\n".join(f"{f} p.{p}" for f, p in hits) or "not found"

    def t_read_pages(self, file, start_page, end_page=None):
        row = self._file(file)
        end_page = min(end_page or start_page, start_page + MAX_READ_PAGES - 1, row["pages"])
        pages = list(range(max(1, start_page), end_page + 1))
        texts = ocr_pages(self.conn, row["id"], pages)
        name = Path(row["path"]).name
        return "\n\n".join(f"===== {name} p.{p} =====\n{texts.get(p, '')}" for p in pages)

    def t_check_ode_solution(self, ode, solution, func="y", var="x"):
        return mathcheck.check_ode(ode, solution, func or "y", var or "x")

    def t_solve_ode(self, ode, ics="", func="y", var="x"):
        return mathcheck.dsolve(ode, ics, func or "y", var or "x")

    def t_math(self, op, expr, var="x", other=""):
        return mathcheck.compute(op, expr, var or "x", other or "")

    def t_run_code(self, language, code, stdin=""):
        return run_code(language, code, stdin)

    def solution_files(self) -> list[Path]:
        return sorted(self.solutions.rglob("*.md")) if self.solutions.is_dir() else []

    def t_list_solution_files(self):
        return "\n".join(str(p.relative_to(self.solutions)) for p in self.solution_files()) or "none yet"

    def t_read_solution_file(self, filename):
        existing = [p for p in self.solution_files() if p.name == Path(filename).name]
        return existing[0].read_text() if existing else "file does not exist"

    def t_write_solution_file(self, filename, content, chapter=None, mode="append"):
        path = self._solution_path(filename, chapter)
        path.parent.mkdir(parents=True, exist_ok=True)
        content = re.sub(r"\A\s*---\s*", "", content)
        if mode == "append" and path.exists() and path.read_text().strip():
            content = path.read_text().rstrip() + "\n\n---\n\n" + content
        path.write_text(content.rstrip() + "\n")
        return f"wrote {path}"

    def t_list_patterns(self):
        rows = patterns.list_all(self.conn, self.course)
        return "\n".join(
            f"{p['slug']}: {p['name']} ({p['sections']}) — spot: {p['recognize']} — {p['solved']} solved"
            + ("" if p["filled"] else " — page EMPTY")
            for p in rows
        ) or "no patterns yet; pass a new pattern name to save_problem to create one"

    def t_get_pattern(self, pattern):
        p = patterns.find(self.conn, self.course, pattern)
        return patterns.to_markdown(self.conn, p) if p else "no such pattern; call list_patterns"

    def t_save_pattern(self, name, body, sections="", recognize=""):
        p = patterns.upsert(self.conn, self.course, name, sections=sections, recognize=recognize, body=body)
        return f"saved pattern {p['slug']} to solutions/patterns/{p['slug']}.md"

    def t_save_problem(self, section, number, title, statement, solution, answer="", verified=False, source="",
                       chapter="", pattern=""):
        pid, created = problems.save(
            self.conn, self.course, section=section, number=number, title=title, statement=statement,
            solution=solution, answer=answer, verified=verified, source=source, chapter=chapter,
        )
        pattern_note = ""
        if pattern.strip():
            pat = patterns.find(self.conn, self.course, pattern) or patterns.upsert(
                self.conn, self.course, pattern, sections=section)
            old = self.conn.execute("SELECT pattern_id FROM problems WHERE id = ?", (pid,)).fetchone()["pattern_id"]
            patterns.tag(self.conn, pid, pat["id"])
            patterns.refresh_file(self.conn, self.course, pat["id"])
            if old and old != pat["id"]:
                patterns.refresh_file(self.conn, self.course, old)
            pattern_note = f"; tagged pattern {pat['slug']}" + ("" if pat["body"] else " (its page is EMPTY: fill it in with save_pattern)")
        p = problems.get(self.conn, pid)
        safe_section = re.sub(r"[^\w.\-]", "_", p["section"])
        block = problems.to_markdown(p)
        path = self._solution_path(f"{safe_section}-solutions.md", p["chapter"])
        text = path.read_text() if path.exists() else ""
        head = re.search(rf"^## Problem {re.escape(str(p['number']))} — .*$", text, re.M)
        if head:
            nxt = re.search(r"^## ", text[head.end():], re.M)
            end = head.end() + nxt.start() if nxt else len(text)
            tail = text[end:]
            sep = "\n\n---\n\n" if tail.strip() else "\n"
            before = text[:head.start()]
            path.write_text(before + block.rstrip() + sep + tail.lstrip("\n"))
            written = f"replaced Problem {p['number']} in {path}"
        else:
            written = self.t_write_solution_file(path.name, block, p["chapter"])
        verb = "saved" if created else "updated"
        return f"{verb} {section} #{number} in the library (id {pid}); {written}{pattern_note}"

    def t_get_saved_problem(self, section, number):
        p = problems.find(self.conn, self.course, section, number)
        return problems.to_markdown(p) if p else "not in the library yet"

    def t_update_profile(self, field, value, action="add"):
        return profile.update(field, value, action)
