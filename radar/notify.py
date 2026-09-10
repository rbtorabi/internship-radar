"""Phone alerts via ntfy (https://ntfy.sh). Install the ntfy app and subscribe to your secret topic."""

import json
import os
import urllib.request

from .models import Job


def _post(server: str, body: dict) -> None:
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        print(f"[notify] NTFY_TOPIC not set, would send: {body['title']}")
        return
    req = urllib.request.Request(
        server.rstrip("/") + "/",
        data=json.dumps({"topic": topic, **body}).encode(),
        headers={"Content-Type": "application/json"},
    )
    urllib.request.urlopen(req, timeout=15).close()


def send_job(cfg: dict, job: Job, reason: str) -> None:
    where = ", ".join(job.locations[:3]) or "Location not listed"
    _post(cfg["notify"]["server"], {
        "title": f"{job.company}: {job.title}"[:200],
        "message": f"{where} ({reason})\nvia {job.source}",
        "click": job.url,
        "priority": 4,
        "tags": ["briefcase"],
        "actions": [{"action": "view", "label": "Apply now", "url": job.url}],
    })


def send_summary(cfg: dict, matches: list[tuple[Job, str]]) -> None:
    lines = [f"- {j.company}: {j.title}" for j, _ in matches[:30]]
    _post(cfg["notify"]["server"], {
        "title": f"{len(matches)} new internship matches",
        "message": "\n".join(lines),
        "priority": 4,
        "tags": ["briefcase"],
    })
