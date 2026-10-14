import argparse
import json
import readline  # noqa: F401  (arrow keys + history in input())

from . import profile
from .config import course_dir


def cmd_ingest(a):
    from .ingest import ingest_course

    ingest_course(a.course)


def cmd_ocr(a):
    from .db import connect
    from .tools import Toolbox

    start, _, end = a.pages.partition("-")
    start, end = int(start), int(end or start)
    box = Toolbox(connect(), a.course.lower())
    for s in range(start, end + 1, 6):
        e = min(s + 5, end)
        text = box.t_read_pages(a.file, s, e)
        print(text if a.show else f"p.{s}-{e} done")


def cmd_search(a):
    from .db import connect
    from .search import hybrid_search

    for h in hybrid_search(connect(), a.course.lower(), a.query, a.k):
        print(f"\n[{h.file} p.{h.page_no}] score={h.score:.4f}\n{h.text[:400]}")


DIM, RESET = "\033[2m", "\033[0m"


def _print_run(tutor, text: str) -> None:
    at_line_start = True
    for ev in tutor.run(text):
        if ev["type"] == "text":
            print(ev["delta"], end="", flush=True)
            at_line_start = ev["delta"].endswith("\n")
        elif ev["type"] == "tool":
            print(("" if at_line_start else "\n") + f"{DIM}  ↳ {ev['name']}({ev['args']}){RESET}", flush=True)
            at_line_start = True
        elif ev["type"] == "error":
            print(f"\nERROR: {ev['message']}")
    if not at_line_start:
        print()


def cmd_ask(a):
    from .agent import Tutor

    _print_run(Tutor(a.course), " ".join(a.question))


def cmd_serve(a):
    import uvicorn

    print(f"Open http://localhost:{a.port}")
    uvicorn.run("tutor.server:app", host="127.0.0.1", port=a.port, log_level="warning")


def cmd_chat(a):
    from .agent import Tutor

    tutor = Tutor(a.course)
    print(f"Tutor for {a.course.upper()}. Commands: /reset (new topic), /exit. Multi-line: end a line with \\")
    while True:
        try:
            lines = [input("\nyou> ")]
            while lines[-1].endswith("\\"):
                lines[-1] = lines[-1][:-1]
                lines.append(input("...  "))
        except (EOFError, KeyboardInterrupt):
            print()
            break
        text = "\n".join(lines).strip()
        if not text:
            continue
        if text == "/exit":
            break
        if text == "/reset":
            tutor.reset()
            print("(conversation cleared)")
            continue
        print()
        try:
            _print_run(tutor, text)
        except KeyboardInterrupt:
            print("\n(interrupted)")


def cmd_import(a):
    from .db import connect
    from .problems import import_markdown

    print(f"added {import_markdown(connect(), a.course.lower())} problems to the library")


def cmd_profile(a):
    print(json.dumps(profile.load(), indent=2))


def main():
    p = argparse.ArgumentParser(prog="tutor", description="Local AI tutor over your course materials")
    sub = p.add_subparsers(required=True)

    s = sub.add_parser("ingest", help="index a course folder (PDFs, .md, .txt) for search")
    s.add_argument("course")
    s.set_defaults(fn=cmd_ingest)

    s = sub.add_parser("ocr", help="pre-transcribe PDF pages (math → LaTeX), e.g. ocr engr213 Zill 176-185")
    s.add_argument("course")
    s.add_argument("file")
    s.add_argument("pages")
    s.add_argument("--show", action="store_true", help="print the transcription")
    s.set_defaults(fn=cmd_ocr)

    s = sub.add_parser("search", help="test retrieval")
    s.add_argument("course")
    s.add_argument("query")
    s.add_argument("-k", type=int, default=5)
    s.set_defaults(fn=cmd_search)

    s = sub.add_parser("ask", help="one question, e.g. ask engr213 solve 2.2 problems 6-10")
    s.add_argument("course")
    s.add_argument("question", nargs="+")
    s.set_defaults(fn=cmd_ask)

    s = sub.add_parser("chat", help="interactive tutoring session")
    s.add_argument("course")
    s.set_defaults(fn=cmd_chat)

    s = sub.add_parser("import-solutions", help="load existing solution .md files into the problem library")
    s.add_argument("course")
    s.set_defaults(fn=cmd_import)

    s = sub.add_parser("serve", help="start the web app")
    s.add_argument("--port", type=int, default=8000)
    s.set_defaults(fn=cmd_serve)

    s = sub.add_parser("profile", help="show the learner profile")
    s.set_defaults(fn=cmd_profile)

    a = p.parse_args()
    if getattr(a, "course", None) and not course_dir(a.course).is_dir():
        p.error(f"no folder {course_dir(a.course)}")
    a.fn(a)


if __name__ == "__main__":
    main()
