"""Fetchers for each applicant-tracking system's public job feed.

Each fetcher returns a list of jobs, or None if the board doesn't exist (dead slug).
"""

import json
import re
import urllib.request
from datetime import datetime, timezone

from .models import Job

HEADERS = {"User-Agent": "internship-radar/1.0 (personal internship alerts)", "Accept": "application/json"}
TIMEOUT = 20


def _get(url: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {**HEADERS, "Content-Type": "application/json"} if data else HEADERS
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=TIMEOUT) as r:
            return json.load(r)
    except Exception:  # 404s, timeouts, bad JSON: across ~29k boards, one bad board must never stop the run
        return None


def _name(slug: str) -> str:
    """"acme-robotics" -> "Acme Robotics" for boards that don't report a company name."""
    return slug.replace("-", " ").replace("_", " ").title()


def greenhouse(slug: str) -> list[Job] | None:
    d = _get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
    if not isinstance(d, dict) or "jobs" not in d:
        return None
    return [
        Job("greenhouse", j.get("company_name") or slug, str(j["id"]), j["title"], j["absolute_url"],
            [n] if (n := (j.get("location") or {}).get("name")) else [],
            posted_at=j.get("first_published"))
        for j in d["jobs"]
    ]


def lever(slug: str) -> list[Job] | None:
    d = _get(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    if not isinstance(d, list):
        return None
    jobs = []
    for j in d:
        c = j.get("categories") or {}
        created = j.get("createdAt")
        jobs.append(Job(
            "lever", _name(slug), j["id"], j["text"], j["hostedUrl"],
            c.get("allLocations") or ([c["location"]] if c.get("location") else []),
            remote=j.get("workplaceType") == "remote",
            posted_at=datetime.fromtimestamp(created / 1000, timezone.utc).isoformat() if created else None,
            intern_flag="intern" in (c.get("commitment") or "").lower(),
        ))
    return jobs


def ashby(slug: str) -> list[Job] | None:
    d = _get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    if not isinstance(d, dict) or "jobs" not in d:
        return None
    jobs = []
    for j in d["jobs"]:
        if j.get("isListed") is False:
            continue
        addr = (j.get("address") or {}).get("postalAddress") or {}
        locs = [j.get("location"), *[s.get("location") for s in j.get("secondaryLocations") or []],
                ", ".join(filter(None, [addr.get("addressLocality"), addr.get("addressRegion"), addr.get("addressCountry")]))]
        jobs.append(Job(
            "ashby", _name(slug), j["id"], j["title"], j["jobUrl"], list(dict.fromkeys(l for l in locs if l)),
            remote=bool(j.get("isRemote")) or j.get("workplaceType") == "Remote",
            posted_at=j.get("publishedAt"),
            intern_flag=j.get("employmentType") == "Intern",
        ))
    return jobs


def workday(entry: str, max_jobs: int = 200) -> list[Job] | None:
    """entry is "tenant|wdN|site". Workday has no list-everything feed, so we search for "intern"."""
    tenant, wd, site = entry.split("|")
    host = f"https://{tenant}.{wd}.myworkdayjobs.com"
    api = f"{host}/wday/cxs/{tenant}/{site}"
    jobs: list[Job] = []
    total = None
    offset = 0
    while offset < max_jobs:
        d = _get(f"{api}/jobs", {"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": "intern"})
        if not isinstance(d, dict):
            return None if offset == 0 else jobs
        if total is None:
            total = d.get("total") or 0  # Workday only reports total on the first page
        posts = d.get("jobPostings") or []
        for p in posts:
            if "title" not in p or "externalPath" not in p:
                continue
            loc = p.get("locationsText") or ""
            multi = bool(re.fullmatch(r"\d+ Locations?", loc))
            jobs.append(Job(
                "workday", tenant, p["externalPath"], p["title"], f"{host}/{site}{p['externalPath']}",
                [] if multi else [loc] if loc else [],
                detail=f"{api}{p['externalPath']}" if multi or not loc else None,
            ))
        offset += 20
        if len(posts) < 20 or offset >= total:
            break
    return jobs


def workday_fill_locations(job: Job) -> None:
    """Workday list results say "3 Locations"; the detail endpoint has the real ones."""
    info = (_get(job.detail) or {}).get("jobPostingInfo") or {}
    job.locations = [l for l in [info.get("location"), *(info.get("additionalLocations") or [])] if l]
    job.remote = job.remote or "remote" in (info.get("remoteType") or "").lower()
    job.posted_at = info.get("startDate")


FETCHERS = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby, "workday": workday}
