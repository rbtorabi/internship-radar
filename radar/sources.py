"""Fetchers for each applicant-tracking system's public job feed.

Each fetcher returns a list of jobs, or None if the board doesn't exist (dead slug).
"""

import json
import re
import urllib.request
from collections import defaultdict
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


ASHBY_TYPES = {"Intern": "internship", "PartTime": "part_time", "FullTime": "full_time", "Contract": "other", "Temporary": "other"}


def _lever_type(commitment: str | None) -> str | None:
    s = (commitment or "").lower()
    if "intern" in s:
        return "internship"
    if "part" in s:
        return "part_time"
    if "full" in s:
        return "full_time"
    if any(w in s for w in ("contract", "fixed", "temp", "freelance", "seasonal")):
        return "other"
    return None


def greenhouse(slug: str) -> list[Job] | None:
    d = _get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
    if not isinstance(d, dict) or "jobs" not in d:
        return None
    return [
        Job("greenhouse", j.get("company_name") or slug, str(j["id"]), j["title"], j["absolute_url"],
            [n] if (n := (j.get("location") or {}).get("name")) else [],
            posted_at=j.get("first_published"), board=slug)
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
            job_type=_lever_type(c.get("commitment")), board=slug,
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
            job_type=ASHBY_TYPES.get(j.get("employmentType")), board=slug,
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


WORKDAY_INTERN = re.compile(r"intern|trainee|co-?op|apprentice|student", re.I)
WORKDAY_OTHER = re.compile(r"contract|temporary|\btemp\b|seasonal|fixed term", re.I)
TYPE_RANK = {"other": 0, "part_time": 1, "internship": 2}  # when a posting is in several groups, the higher wins


def _age_days(posted_on: str | None) -> int | None:
    """"Posted Today" -> 0, "Posted 3 Days Ago" -> 3, "Posted 30+ Days Ago" -> 30."""
    s = (posted_on or "").lower()
    if "today" in s:
        return 0
    if "yesterday" in s:
        return 1
    m = re.search(r"(\d+)\+?\s*days?", s)
    return int(m.group(1)) if m else None


def _workday_list(api: str, facets: dict, max_age_days: int) -> tuple[dict | None, list[dict]]:
    """Postings newest-first, stopping after two whole pages older than max_age_days (Workday caps results at 2000)."""
    first, posts, old_pages, total = None, [], 0, 0
    for offset in range(0, 2000, 20):
        d = _get(f"{api}/jobs", {"appliedFacets": facets, "limit": 20, "offset": offset, "searchText": ""})
        if not isinstance(d, dict):
            break
        if first is None:
            first, total = d, d.get("total") or 0  # Workday only reports total on the first page
        page = d.get("jobPostings") or []
        posts += page
        ages = [_age_days(p.get("postedOn")) for p in page]
        old_pages = old_pages + 1 if ages and all(a is not None and a >= max_age_days for a in ages) else 0
        if len(page) < 20 or old_pages >= 2 or offset + 20 >= total:
            break
    return first, posts


def workday_all(entry: str, max_age_days: int = 30) -> list[Job] | None:
    """Every recent posting on a Workday board, typed using the board's own Time Type / Worker Sub-Type filters."""
    tenant, wd, site = entry.split("|")
    host = f"https://{tenant}.{wd}.myworkdayjobs.com"
    api = f"{host}/wday/cxs/{tenant}/{site}"
    first, posts = _workday_list(api, {}, max_age_days)
    if first is None:
        return None

    labels: dict[str, str] = {}
    has_time_type = False
    for facet in first.get("facets") or []:
        param = facet.get("facetParameter")
        if param not in ("timeType", "workerSubType"):
            continue
        has_time_type |= param == "timeType"
        groups: dict[str, list[str]] = defaultdict(list)
        for v in facet.get("values") or []:
            name = v.get("descriptor") or ""
            if not v.get("id") or not v.get("count"):
                continue
            if param == "timeType" and "part" in name.lower():
                groups["part_time"].append(v["id"])
            elif param == "workerSubType" and WORKDAY_INTERN.search(name):
                groups["internship"].append(v["id"])
            elif param == "workerSubType" and WORKDAY_OTHER.search(name):
                groups["other"].append(v["id"])
        for label, ids in groups.items():
            for p in _workday_list(api, {param: ids}, max_age_days)[1]:
                path = p.get("externalPath")
                if path and TYPE_RANK[label] > TYPE_RANK.get(labels.get(path, ""), -1):
                    labels[path] = label

    jobs = []
    for p in posts:
        if "title" not in p or "externalPath" not in p:
            continue
        path = p["externalPath"]
        loc = p.get("locationsText") or ""
        multi = bool(re.fullmatch(r"\d+ Locations?", loc))
        jobs.append(Job(
            "workday", _name(tenant), path, p["title"], f"{host}/{site}{path}",
            [] if multi or not loc else [loc],
            detail=f"{api}{path}" if multi or not loc else None,
            job_type=labels.get(path) or ("full_time" if has_time_type else None),
            board=entry, age_days=_age_days(p.get("postedOn")),
        ))
    return jobs


def workday_fill_locations(job: Job) -> None:
    """Workday list results say "3 Locations" or nothing; the detail endpoint usually has the real ones."""
    info = (_get(job.detail) or {}).get("jobPostingInfo") or {}
    req = info.get("jobRequisitionLocation") or {}
    locs = [info.get("location"), *(info.get("additionalLocations") or []),
            req.get("descriptor") if isinstance(req, dict) else req,
            (info.get("country") or (req.get("country") if isinstance(req, dict) else None) or {}).get("descriptor")]
    locs = [l for l in locs if isinstance(l, str) and l.strip()]
    parts = job.id.strip("/").split("/")  # id is the externalPath: job/<Location>/<Title_ID> or job/<Title_ID>
    if not locs and len(parts) == 3:
        locs = [parts[1].replace("-", " ")]
    job.locations = list(dict.fromkeys(locs))
    job.remote = job.remote or "remote" in (info.get("remoteType") or "").lower()
    job.posted_at = info.get("startDate")


FETCHERS = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby, "workday": workday}
