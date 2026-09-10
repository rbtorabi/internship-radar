"""Internship Radar.

    python -m radar.main sweep   # every company (~29k boards, ~20 min); rebuilds the hot list
    python -m radar.main poll    # only hot companies (ones with jobs near you); takes seconds
"""

import json
import os
import sys
import time
import tomllib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from . import notify, sources, state
from .filters import Filter
from .models import Job


def load_config() -> dict:
    cfg = tomllib.loads(Path("config.toml").read_text(encoding="utf-8"))
    # Lets a public repo keep your city out of config.toml: set these as GitHub secrets/variables instead.
    loc = cfg["location"]
    if city := os.environ.get("LOCATION"):
        loc["city"] = city
    if radius := os.environ.get("LOCATION_RADIUS_KM"):
        loc["radius_km"] = float(radius)
    if kw := os.environ.get("LOCATION_KEYWORDS"):
        loc["keywords"] = [k.strip() for k in kw.split(",") if k.strip()]
    return cfg


def write_step_summary(mode: str, stats: str, matches: list[tuple[Job, str]]) -> None:
    lines = [f"### Internship Radar ({mode})", stats, ""]
    if matches:
        lines += ["| Company | Role | Location | Why |", "|---|---|---|---|"]
        lines += [f"| {j.company} | [{j.title}]({j.url}) | {', '.join(j.locations[:3]) or '?'} | {r} |" for j, r in matches]
    print("\n".join(lines))
    if path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")


def main(mode: str) -> None:
    cfg = load_config()
    if not cfg["location"]["city"] and not cfg["location"]["keywords"]:
        sys.exit('Set your city: the LOCATION secret (e.g. "Toronto, Canada") or [location] city in config.toml.')
    sources.TIMEOUT = cfg["scan"]["timeout_seconds"]
    try:
        flt = Filter(cfg)
    except ValueError as e:
        sys.exit(str(e))
    if flt.area:
        towns = ", ".join(c.name for c in flt.area.nearby[:12])
        print(f"Local = within {cfg['location']['radius_km']:g} km of {flt.area.home} "
              f"({len(flt.area.nearby)} places: {towns}{'...' if len(flt.area.nearby) > 12 else ''})")

    seen_list = state.load("seen")
    first_run = seen_list is None
    seen = set(seen_list or [])
    hot = state.load("hot")
    if mode == "poll" and hot is None:
        mode = "sweep"  # no hot list yet

    if mode == "sweep":
        boards = {src: json.loads(Path(f"companies/{src}.json").read_text(encoding="utf-8")) for src in sources.FETCHERS}
    else:
        boards = hot

    started = time.time()
    tasks = [(src, board) for src, bs in boards.items() for board in bs]
    with ThreadPoolExecutor(cfg["scan"]["workers"]) as ex:
        results = list(ex.map(lambda t: sources.FETCHERS[t[0]](t[1]), tasks))

    new_hot: dict[str, list[str]] = {src: [] for src in sources.FETCHERS}
    live = 0
    candidates: list[Job] = []
    for (src, board), jobs in zip(tasks, results):
        if jobs is None:
            if mode == "sweep" and board in (hot or {}).get(src, []):
                new_hot[src].append(board)  # probably a timeout; don't drop a hot company for one bad request
            continue
        live += 1
        if any(flt.where(j) for j in jobs):
            new_hot[src].append(board)
        for job in jobs:
            # Only internship-shaped titles are remembered, which keeps state small.
            if flt.title_ok(job.title, job.intern_flag) and job.key not in seen:
                seen.add(job.key)
                candidates.append(job)

    with ThreadPoolExecutor(cfg["scan"]["workers"]) as ex:
        list(ex.map(sources.workday_fill_locations, [j for j in candidates if j.detail]))
    matches = [(j, reason) for j in candidates if (reason := flt.where(j))]

    stats = (f"{len(tasks)} boards checked, {live} live, {len(candidates)} new internship titles, "
             f"{len(matches)} match your location, {time.time() - started:.0f}s")
    write_step_summary(mode, stats, matches)

    if first_run or len(matches) > cfg["notify"]["max_per_run"]:
        if matches:
            notify.send_summary(cfg, matches)
    else:
        for job, reason in matches:
            notify.send_job(cfg, job, reason)

    # Saved only after alerts went out, so a failed run retries instead of silently skipping jobs.
    state.save("seen", sorted(seen))
    if mode == "sweep":
        state.save("hot", new_hot)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    history = state.load("history", [])
    history += [{"found_at": now, "posted_at": j.posted_at, "company": j.company, "title": j.title,
                 "url": j.url, "locations": j.locations, "reason": r, "source": j.source} for j, r in matches]
    state.save("history", history)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "poll")
