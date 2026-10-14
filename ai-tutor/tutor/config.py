import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

MATERIALS_DIR = Path(os.getenv("MATERIALS_DIR", "~/f26")).expanduser()
SOLUTIONS_SUBDIR = "solutions"
RULE_FILE = Path(os.getenv("RULE_FILE", "~/f26/.cursor/rules/tutor.mdc")).expanduser()
DATA_DIR = ROOT / "data"
PROMPTS_DIR = ROOT / "prompts"
DB_PATH = DATA_DIR / "tutor.db"
PROFILE_PATH = DATA_DIR / "profile.json"
SESSIONS_DIR = DATA_DIR / "sessions"

API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
FAST_MODEL = os.getenv("DEEPSEEK_FAST_MODEL", "deepseek-flash")
EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-small-en-v1.5")

CHUNK_CHARS = 1200
CHUNK_OVERLAP = 200

for d in (DATA_DIR, SESSIONS_DIR):
    d.mkdir(parents=True, exist_ok=True)


def course_dir(course: str) -> Path:
    return MATERIALS_DIR / course.lower()


def solutions_dir(course: str) -> Path:
    return course_dir(course) / SOLUTIONS_SUBDIR
