"""Decides whether a job is an internship worth alerting on."""

import re

from .geo import Area
from .models import Job

# \bintern\b does not match "internal" or "international".
INTERN = re.compile(
    r"\b(intern|interns|internship|co-?op|summer student|student (researcher|developer|engineer)"
    r"|apprentice(ship)?|werkstudent)\b",
    re.I,
)
YEAR = re.compile(r"\b20[2-3]\d\b")
REMOTE = re.compile(r"\b(remote|anywhere|work from home|wfh)\b", re.I)


class Filter:
    def __init__(self, cfg: dict):
        self.include = re.compile(cfg["roles"]["include"], re.I)
        self.exclude = re.compile(cfg["roles"]["exclude"], re.I)
        self.years = set(cfg["profile"]["target_years"])
        loc = cfg["location"]
        self.area = Area(loc["city"], loc["radius_km"]) if loc.get("city") else None
        self.places = [re.compile(rf"\b{re.escape(k)}\b", re.I) for k in loc["keywords"]]
        self.include_remote = loc["include_remote"]
        self.include_unknown = loc["include_unknown"]

    def title_ok(self, title: str, intern_flag: bool = False) -> bool:
        if not (intern_flag or INTERN.search(title)):
            return False
        if not self.include.search(title) or self.exclude.search(title):
            return False
        years = {int(y) for y in YEAR.findall(title)}
        return not years or bool(years & self.years)

    def is_local(self, text: str) -> bool:
        return bool((self.area and self.area.matches(text)) or any(p.search(text) for p in self.places))

    def match(self, job: Job) -> str | None:
        """Returns why the job matched ("local", "remote", "location not listed"), or None to skip it."""
        return self.where(job) if self.title_ok(job.title, job.intern_flag) else None

    def where(self, job: Job) -> str | None:
        """Location check only, for any role."""
        where = " | ".join(job.locations)
        if self.is_local(where):
            return "local"
        if job.remote or REMOTE.search(where):
            return "remote" if self.include_remote else None
        if not where.strip():
            return "location not listed" if self.include_unknown else None
        return None
