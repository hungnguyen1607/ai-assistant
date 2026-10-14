import json
import threading
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import outline, problems, profile
from .agent import Tutor
from .config import MATERIALS_DIR, ROOT, solutions_dir
from .db import connect

WEB_DIST = ROOT / "web" / "dist"
SKIP_DIRS = {"solutions", ROOT.name}

app = FastAPI(title="AI Tutor")
sessions: dict[str, tuple[Tutor, threading.Lock]] = {}


class NewSession(BaseModel):
    course: str


class Message(BaseModel):
    text: str


def _course(course: str) -> str:
    course = course.lower()
    if course in SKIP_DIRS or not (MATERIALS_DIR / course).is_dir():
        raise HTTPException(404, f"no course folder {MATERIALS_DIR / course}")
    return course


def _session(session_id: str) -> tuple[Tutor, threading.Lock]:
    if session_id not in sessions:
        raise HTTPException(404, "session expired; start a new one")
    return sessions[session_id]


@app.get("/api/courses")
def courses():
    conn = connect()
    counts = dict(conn.execute("SELECT course, COUNT(*) FROM files GROUP BY course").fetchall())
    dirs = sorted(p.name for p in MATERIALS_DIR.iterdir() if p.is_dir() and not p.name.startswith(".") and p.name not in SKIP_DIRS)
    return [{"id": d, "files": counts.get(d, 0)} for d in dirs]


@app.get("/api/courses/{course}/materials")
def materials(course: str):
    root = MATERIALS_DIR / _course(course)
    rows = connect().execute("SELECT path, pages FROM files WHERE course = ? ORDER BY path", (course.lower(),))
    return [{"name": str(Path(r["path"]).relative_to(root)), "pages": r["pages"]} for r in rows]


@app.get("/api/courses/{course}/outline")
def course_outline(course: str, refresh: bool = False):
    try:
        return outline.get(connect(), _course(course), refresh)
    except RuntimeError as e:
        raise HTTPException(502, str(e))


def _chapter_key(group: str) -> tuple:
    num = group.removeprefix("chapter-")
    return (0, int(num), "") if num.isdigit() else (1, 0, group)


@app.get("/api/courses/{course}/solutions")
def solutions(course: str):
    root = solutions_dir(_course(course))
    files = sorted(root.rglob("*.md")) if root.is_dir() else []
    out = [
        {
            "name": p.name,
            "path": str(p.relative_to(root)),
            "group": str(p.parent.relative_to(root)) if p.parent != root else "",
            "modified": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="minutes"),
        }
        for p in files
    ]
    return sorted(out, key=lambda f: (_chapter_key(f["group"]), f["name"]))


@app.get("/api/courses/{course}/solutions/{path:path}")
def solution_file(course: str, path: str):
    root = solutions_dir(_course(course)).resolve()
    file = (root / path).resolve()
    if not file.is_relative_to(root) or file.suffix != ".md" or not file.is_file():
        raise HTTPException(404, "no such file")
    return {"name": file.name, "path": str(file.relative_to(root)), "content": file.read_text()}


@app.get("/api/courses/{course}/problems")
def list_problems(course: str):
    return problems.list_all(connect(), _course(course))


@app.get("/api/problems/{problem_id}")
def get_problem(problem_id: int):
    p = problems.get(connect(), problem_id)
    if not p:
        raise HTTPException(404, "no such problem")
    return p


@app.delete("/api/problems/{problem_id}")
def delete_problem(problem_id: int):
    if not problems.delete(connect(), problem_id):
        raise HTTPException(404, "no such problem")
    return {"ok": True}


@app.get("/api/profile")
def get_profile():
    return profile.load()


@app.post("/api/sessions")
def new_session(body: NewSession):
    session_id = uuid.uuid4().hex
    sessions[session_id] = (Tutor(_course(body.course), interface="web"), threading.Lock())
    return {"session_id": session_id}


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str):
    tutor, _ = _session(session_id)
    return {"course": tutor.course, "messages": tutor.history()}


@app.post("/api/sessions/{session_id}/reset")
def reset_session(session_id: str):
    tutor, _ = _session(session_id)
    tutor.reset()
    return {"ok": True}


@app.post("/api/sessions/{session_id}/messages")
def send_message(session_id: str, body: Message):
    tutor, lock = _session(session_id)
    if not lock.acquire(blocking=False):
        raise HTTPException(409, "the tutor is still answering the previous message")

    def events():
        # a sync generator: Starlette iterates it in a worker thread, so blocking API calls are fine
        try:
            for ev in tutor.run(body.text):
                yield f"data: {json.dumps(ev)}\n\n"
        finally:
            lock.release()

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


if WEB_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        file = WEB_DIST / path
        return FileResponse(file if path and file.is_file() else WEB_DIST / "index.html")
