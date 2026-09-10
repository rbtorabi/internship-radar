"""Turns a fetched Job into the fields the befirst app filters on."""

import re
from datetime import datetime, timezone

from .filters import REMOTE
from .geo import USLocator
from .models import Job

INTERN = re.compile(r"\b(intern|interns|internship|co-?op|apprentice(ship)?|trainee|summer (student|analyst|associate))\b", re.I)
PART_TIME = re.compile(r"\bpart[- ]?time\b", re.I)
OTHER = re.compile(r"\b(contract(or)?|temporary|temp|freelance|seasonal|per diem|prn)\b", re.I)


def job_type(job: Job) -> str:
    """internship | part_time | full_time | other. The title wins when it says so; otherwise trust the ATS label."""
    if INTERN.search(job.title) or job.job_type == "internship":
        return "internship"
    if PART_TIME.search(job.title):
        return "part_time"
    if job.job_type:
        return job.job_type
    return "other" if OTHER.search(job.title) else "full_time"


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def place(locator: USLocator, job: Job) -> tuple[list[int], bool | None, bool]:
    """Returns (US city ids, True = US / False = abroad / None = unknown, remote)."""
    city_ids: dict[int, None] = {}
    verdicts = []
    for loc in job.locations:
        found, us = locator.locate(loc)
        city_ids.update((c.gid, None) for c in found)
        verdicts.append(us)
    remote = job.remote or any(REMOTE.search(l) for l in job.locations)
    if any(v is True for v in verdicts):
        us = True
    elif verdicts and all(v is False for v in verdicts):
        us = False
    else:
        us = None
    return list(city_ids), us, remote
