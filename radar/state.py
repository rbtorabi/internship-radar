"""JSON files under state/ that persist between runs (restored from the GitHub Actions cache)."""

import json
from pathlib import Path

DIR = Path("state")


def load(name: str, default=None):
    path = DIR / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save(name: str, value) -> None:
    DIR.mkdir(exist_ok=True)
    (DIR / f"{name}.json").write_text(json.dumps(value), encoding="utf-8")
