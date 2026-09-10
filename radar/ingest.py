"""befirst job engine: fetch every recent US job posting and sync it into Postgres for the web app.

    python -m radar.ingest sweep                        # every company board
    python -m radar.ingest poll                         # boards with postings in the last few days
    python -m radar.ingest sweep --dry-run --limit 200  # no database: sample 200 boards per source, print results
"""

import argparse
import json
import os
import random
import sys
import time
import tomllib
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import sources
from .geo import USLocator
from .normalize import job_type, parse_time, place

FETCH = {"greenhouse": sources.greenhouse, "lever": sources.lever, "ashby": sources.ashby, "workday": sources.workday_all}


def load_dotenv(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("\"'")
        if sep and key and not key.startswith("#") and value:
            os.environ.setdefault(key, value)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["sweep", "poll"])
    ap.add_argument("--dry-run", action="store_true", help="don't touch the database")
    ap.add_argument("--limit", type=int, help="only this many random boards per source (testing)")
    args = ap.parse_args()

    load_dotenv()
    cfg = tomllib.loads(Path("config.toml").read_text(encoding="utf-8"))
    ing = cfg["ingest"]
    sources.TIMEOUT = cfg["scan"]["timeout_seconds"]
    url = os.environ.get("DATABASE_URL")
    if not url and not args.dry_run:
        sys.exit("DATABASE_URL is not set: paste it into .env (or run with --dry-run).")

    locator = USLocator()
    conn = None
    if not args.dry_run:
        from . import db
        conn = db.connect(url)
        db.ensure_schema(conn, locator.cities)

    mode = args.mode
    boards = db.hot_boards(conn, ing["hot_days"]) if mode == "poll" and conn else {}
    if not boards:
        mode = "sweep"
        boards = {s: json.loads(Path(f"companies/{s}.json").read_text(encoding="utf-8")) for s in FETCH}
    if args.limit:
        boards = {s: random.sample(b, min(args.limit, len(b))) for s, b in boards.items()}

    started = time.time()
    tasks = [(s, b) for s, bs in boards.items() for b in bs]
    with ThreadPoolExecutor(cfg["scan"]["workers"]) as ex:
        results = list(ex.map(lambda t: FETCH[t[0]](t[1]), tasks))
    ok = [(s, b, jobs) for (s, b), jobs in zip(tasks, results) if jobs is not None]
    board_keys = [f"{s}:{b}" for s, b, _ in ok]
    known = db.existing_uids(conn, board_keys) if conn else set()
    fetch_seconds = time.time() - started

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=ing["max_age_days"])

    # Workday "3 Locations" postings need one request each: only for new ones, capped per run (the rest wait for the next run).
    need_detail = [j for s, b, jobs in ok for j in jobs
                   if j.detail and f"{s}:{b}:{j.id}" not in known and (j.age_days or 0) < ing["max_age_days"]]
    need_detail = need_detail[: ing["detail_budget"]]
    with ThreadPoolExecutor(cfg["scan"]["workers"]) as ex:
        list(ex.map(sources.workday_fill_locations, need_detail))
    filled = {id(j) for j in need_detail}

    rows: list[tuple] = []
    present: set[str] = set()
    counts: Counter = Counter()
    for s, b, jobs in ok:
        staged, board_in_us = [], False
        for j in jobs:
            uid = f"{s}:{b}:{j.id}"
            if j.age_days is not None:  # Workday: day precision, so a brand-new posting gets "now"
                posted = now if j.age_days == 0 and uid not in known else now - timedelta(days=j.age_days)
            else:
                posted = parse_time(j.posted_at) or now
            if posted <= cutoff:
                counts["skipped: older than %d days" % ing["max_age_days"]] += 1
                continue
            if j.detail and id(j) not in filled:
                if uid in known:
                    present.add(uid)  # unchanged multi-location posting: keep what's stored
                else:
                    counts["skipped: waiting for location details"] += 1
                continue
            city_ids, in_us, remote = place(locator, j)
            if in_us is False:
                counts["skipped: outside the US"] += 1
                continue
            board_in_us |= in_us is True
            staged.append((in_us, (uid, s, f"{s}:{b}", j.company, j.title, j.url, job_type(j), remote, j.locations, posted, city_ids)))
        for in_us, row in staged:
            if in_us is None and not board_in_us:  # no location and the company has no US jobs: almost always abroad
                counts["skipped: location unknown"] += 1
                continue
            rows.append(row)
            present.add(row[0])
            counts[row[6]] += 1

    stats = db.write(conn, rows, present, board_keys, ing["max_age_days"]) if conn else {"database": "dry run, nothing written"}
    print(f"befirst ingest ({mode}): {len(tasks)} boards, {len(ok)} live, fetched in {fetch_seconds:.0f}s, "
          f"{len(need_detail)} Workday detail lookups, total {time.time() - started:.0f}s")
    print("kept:", {k: counts[k] for k in ("internship", "part_time", "full_time", "other")}, f"= {len(rows)} US jobs")
    print("skipped:", {k.removeprefix("skipped: "): v for k, v in counts.items() if k.startswith("skipped")})
    print("database:", stats)
    if args.dry_run:
        for row in random.sample(rows, min(15, len(rows))):
            cities = ", ".join(f"{locator.by_gid[g].name} {locator.by_gid[g].admin1}" for g in row[10][:3])
            print(f"  [{row[6]:10}] {row[3][:22]:22} | {row[4][:48]:48} | {cities or '-'} | {'remote ' if row[7] else ''}{row[9]:%Y-%m-%d}")


if __name__ == "__main__":
    main()
