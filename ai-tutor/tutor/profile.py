import json

from .config import PROFILE_PATH

DEFAULT = {
    "name": "Hung",
    "level": "2nd-year software engineering, Concordia",
    "style": "plain English, casual, short sentences, concrete example before any formula",
    "known_terms": [],
    "weak_spots": [],
    "feedback": [],
}


def load() -> dict:
    if PROFILE_PATH.exists():
        return {**DEFAULT, **json.loads(PROFILE_PATH.read_text())}
    return dict(DEFAULT)


def update(field: str, value: str, action: str = "add") -> str:
    profile = load()
    if field not in profile:
        return f"ERROR: unknown field '{field}', use one of {', '.join(profile)}"
    if isinstance(profile[field], list):
        items = profile[field]
        if action == "add" and value not in items:
            items.append(value)
        elif action == "remove" and value in items:
            items.remove(value)
    else:
        profile[field] = value
    PROFILE_PATH.write_text(json.dumps(profile, indent=2))
    return f"profile.{field} updated"
