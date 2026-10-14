from functools import lru_cache

from openai import OpenAI

from .config import API_KEY, BASE_URL


@lru_cache(maxsize=1)
def client() -> OpenAI:
    if not API_KEY:
        raise SystemExit("DEEPSEEK_API_KEY is missing from ~/ai-tutor/.env")
    return OpenAI(api_key=API_KEY, base_url=BASE_URL, timeout=300)
