import json
import re
import time
from collections.abc import Iterator
from datetime import date

from . import profile
from .config import MODEL, PROMPTS_DIR, RULE_FILE, SESSIONS_DIR
from .db import connect
from .llm import client
from .tools import SCHEMAS, Toolbox

MAX_TOOL_ROUNDS = 30
WRAP_UP_ROUNDS = 6
WRAP_UP_NOTE = (
    "\n\n[Tool budget almost used up. Stop verifying: save every problem you've solved now with save_problem "
    "(verified=false for anything not confirmed), then reply.]"
)

APP_INSTRUCTIONS = """
## How you work inside this app

You are running as a local {interface} app for course **{course}**. Today is {today}.
You can't see the course files directly; use the tools.

- Never guess a problem statement. Find it (find_in_materials for "2.2 Exercises"-style phrases,
  search_materials for topics), then read_pages to get the exact text with LaTeX math.
- Textbook PDF page numbers differ from the printed page numbers; always use the PDF page numbers from tools.
- Odd-numbered answers are usually in the textbook's answer section; you may compare against them.
- Check how the course's slides do a method before teaching it, so you use the professor's method.
- Read LaTeX from read_pages literally: e^xy and e^{{x}}y mean e^x·y, while e^{{xy}} means e^(xy). If a
  statement looks ambiguous, re-read that page before solving.
- Verify every final math answer with check_ode_solution / solve_ode / math before saving it. If SymPy says
  NOT VERIFIED, look for a real mistake. If a check fails twice because of a tool/parse error (not a math
  mismatch), stop retrying: check it by hand in the solution and save with verified=false.
  Never present an unverified answer as verified. Save each problem as soon as it's done, not all at the end.
- Code problems: run every version with run_code on a small test before writing it down.
- Every problem you solve, in any chapter, must be saved with save_problem, one call per problem, before you
  reply. It writes the chapter's solution file (solutions/chapter-N/<section>-solutions.md) and replaces the
  old entry if that problem was saved before. Never skip saving, even for a quick answer. Check
  get_saved_problem first so you don't redo a saved problem unless asked; if asked, save the new version.
  If a saved problem has no **Variations:** part yet, add it and re-save.
- Every saved solution ends with a **Variations:** part: 2-4 bullets, each a way this problem type gets
  changed on tests (different form, extra condition, reversed question), how to spot it, and what changes in
  the method. Then one line **Most likely on the exam:** naming the variation and why. Base "likely" on
  evidence in this order: past exams in exams/, the outline, how much lecture time the slides give it,
  assigned problems. Say which evidence you used; if there are no past exams, say it's a guess from the
  slides and outline. Copy the problem statement exactly from read_pages. Use write_solution_file only for things that
  aren't single problems (notes, Anki cards, pattern summaries). Look at read_solution_file once to match the
  existing style. Solutions use plain Unicode math (dy/dx, x², e^(3x), ∫, √) inside code blocks, never LaTeX.
- Graded assignments (files in assignments/, or anything Hung says is graded): don't save their solutions.
  Save a worked similar problem instead, with section like 'A3-practice' and the chapter it belongs to.
- Patterns (LeetCode-style problem types): call list_patterns once before your first save_problem in a
  conversation, and tag every saved problem with the pattern it mainly uses (reuse an existing slug; only
  invent a new pattern if none fits). In the solution, name the pattern and say what in the question gave it
  away. If save_problem says the pattern page is EMPTY, fill it in with save_pattern right after (research the
  textbook section and slides first). "Fill in pattern X": research and save_pattern. "Drill pattern X":
  get_pattern, then give a fresh exercise of that type from its sections that isn't solved yet (prefer the
  most likely exam variation), let Hung try first, then solve and save it.
- Teaching an outline section or week ("Teach me section 1.1 ..." / "Teach me week N: ..."): Hung is learning
  it for the first time. Read the textbook section (if PDF pages are given, read_pages them directly in
  chunks; otherwise find the section start with find_in_materials) and the matching
  lecture slides, and teach in the professor's order and notation. Go one idea at a time: plain-English
  meaning, the definition, a small example, then the common trap. Keep each reply to one or two ideas and
  end with a quick check question; continue when he answers or says next. After the last idea, practice:
  if the outline's suggested problems are given, work through those in order, one at a time (let him try
  first, then show the full solution); otherwise pick 3 from the section's exercises (easy → exam level).
  Save each with save_problem once solved; skip ones already in the library and show the saved version. Save the lesson notes with write_solution_file as '<first section>-notes.md'.
- Cheat sheets (for a midterm, final or quiz): if the chapters aren't given, get the exam coverage from the
  outline. Call list_patterns and organize the sheet by pattern within each topic. Search exams/, lectures/
  and the textbook for each topic. Per topic/pattern, give: key formulas and
  definitions, the method as short steps, the problem variations with how to recognize each and a
  likelihood (High/Medium/Low, with the evidence), one tiny worked example of the most likely variation,
  and common mistakes. End with a "Most likely to come up" list ranked across all topics. Keep it dense
  enough to fit a page or two. Save it with write_solution_file, chapter='cheatsheets', mode='overwrite',
  filename like 'midterm-ch1-3-cheatsheet.md', then give a short summary in chat.
- {chat_math}
- When Hung says something is confusing, or shows he now knows a term, call update_profile.

## Learner profile
{profile}

## Course materials
{materials}
"""

CHAT_MATH = {
    "terminal": "In chat, write math in plain Unicode like the solution files, not LaTeX. "
                "Keep chat replies short when the work is in a file.",
    "web": "In chat, write math in LaTeX ($...$ inline, $$...$$ display); the page renders it. "
           "Keep chat replies short when the work is in a file.",
}


def _rule_text() -> str:
    text = RULE_FILE.read_text() if RULE_FILE.exists() else ""
    return re.sub(r"\A---.*?---\s*", "", text, flags=re.S)


def _course_prompt(course: str) -> str:
    files = sorted(PROMPTS_DIR.glob(f"{course}*.md"))
    return "\n\n".join(p.read_text() for p in files)


class Tutor:
    """One tutoring conversation. `run()` yields events: text, tool, tool_result, done, error."""

    def __init__(self, course: str, interface: str = "terminal"):
        self.course = course.lower()
        self.interface = interface
        self.conn = connect()
        self.tools = Toolbox(self.conn, self.course)
        self.session_file = SESSIONS_DIR / f"{self.course}-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
        self.messages = [{"role": "system", "content": self._system_prompt()}]

    def _system_prompt(self) -> str:
        parts = [_rule_text(), _course_prompt(self.course), APP_INSTRUCTIONS.format(
            interface=self.interface,
            course=self.course.upper(),
            today=date.today().isoformat(),
            chat_math=CHAT_MATH[self.interface],
            profile=json.dumps(profile.load(), indent=2),
            materials=self.tools.t_list_materials(),
        )]
        return "\n\n".join(p for p in parts if p)

    def reset(self) -> None:
        self.messages = [{"role": "system", "content": self._system_prompt()}]

    def history(self) -> list[dict]:
        """User/assistant text turns, for redisplaying a conversation."""
        return [
            {"role": m["role"], "content": m["content"]}
            for m in self.messages[1:]
            if m["role"] in ("user", "assistant") and m.get("content")
        ]

    def run(self, text: str) -> Iterator[dict]:
        self.messages.append({"role": "user", "content": text})
        try:
            for round_no in range(MAX_TOOL_ROUNDS):
                msg = yield from self._stream_turn(allow_tools=round_no < MAX_TOOL_ROUNDS - 1)
                self.messages.append(msg)
                if not msg.get("tool_calls"):
                    yield {"type": "done"}
                    return
                for call in msg["tool_calls"]:
                    name, args = call["function"]["name"], call["function"]["arguments"]
                    yield {"type": "tool", "id": call["id"], "name": name, "args": _short(args)}
                    result = self.tools.call(name, args)
                    ok = not result.startswith(("ERROR", "NOT VERIFIED"))
                    if round_no >= MAX_TOOL_ROUNDS - WRAP_UP_ROUNDS:
                        result += WRAP_UP_NOTE
                    self.messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
                    yield {"type": "tool_result", "id": call["id"], "name": name, "ok": ok}
            yield {"type": "error", "message": "stopped: too many tool calls"}
        except GeneratorExit:
            self._close_pending_tool_calls()
            self.messages.append({"role": "assistant", "content": "(interrupted by user)"})
            raise
        except Exception as exc:
            yield {"type": "error", "message": f"{type(exc).__name__}: {exc}"}
        finally:
            self._log()

    def _stream_turn(self, allow_tools: bool = True) -> Iterator[dict]:
        stream = client().chat.completions.create(
            model=MODEL, messages=self.messages, tools=SCHEMAS, stream=True,
            tool_choice="auto" if allow_tools else "none",
        )
        content, reasoning, calls = [], [], {}
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if getattr(delta, "reasoning_content", None):
                reasoning.append(delta.reasoning_content)
            if delta.content:
                content.append(delta.content)
                yield {"type": "text", "delta": delta.content}
            for tc in delta.tool_calls or []:
                entry = calls.setdefault(tc.index, {"id": "", "name": "", "args": ""})
                entry["id"] = tc.id or entry["id"]
                if tc.function and tc.function.name:
                    entry["name"] = tc.function.name
                if tc.function and tc.function.arguments:
                    entry["args"] += tc.function.arguments
        msg = {"role": "assistant", "content": "".join(content) or None}
        if reasoning:
            msg["reasoning_content"] = "".join(reasoning)
        if calls:
            msg["tool_calls"] = [
                {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c["args"]}}
                for c in calls.values()
            ]
        return msg

    def _close_pending_tool_calls(self) -> None:
        # the API rejects a history where a tool call has no matching tool result
        last = next((m for m in reversed(self.messages) if m["role"] == "assistant"), None)
        if not last or not last.get("tool_calls"):
            return
        answered = {m.get("tool_call_id") for m in self.messages if m["role"] == "tool"}
        for call in last["tool_calls"]:
            if call["id"] not in answered:
                self.messages.append({"role": "tool", "tool_call_id": call["id"], "content": "(interrupted)"})

    def _log(self) -> None:
        with self.session_file.open("w") as f:
            for m in self.messages[1:]:
                f.write(json.dumps({k: v for k, v in m.items() if k != "reasoning_content"}) + "\n")


def _short(args: str, limit: int = 90) -> str:
    try:
        parsed = json.loads(args or "{}")
        text = ", ".join(f"{k}={v!r}" for k, v in parsed.items() if k != "content")
    except json.JSONDecodeError:
        text = args
    return text if len(text) <= limit else text[: limit - 1] + "…"
