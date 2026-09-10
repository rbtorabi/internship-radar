# Internship Radar

Sends a notification to your phone within minutes of a matching internship being posted, so you can be one of the first applicants.

Job boards like LinkedIn and Indeed pick up postings hours or days late. Most companies post first to their applicant-tracking system (Greenhouse, Lever, Ashby, Workday), and those systems have public job feeds. This project reads those feeds directly for **~29,000 company boards**, filters for software/data/AI internships near you, and sends each new match to your phone through [ntfy](https://ntfy.sh).

## How it works

| Run | When | What |
|---|---|---|
| **sweep** | every 6 hours | Checks every company board (~20 min). Saves a *hot list* of companies with any job in your area. |
| **poll** | every 10 minutes | Checks only the hot list (seconds). New matches are sent right away. |

- Each posting alerts **once**. Already-seen jobs are kept in `state/`, which is stored in the GitHub Actions cache rather than committed.
- Every run's matches also appear as a table on the run's page in the **Actions** tab.
- The filter lives in [`config.toml`](config.toml): role keywords, excluded titles (senior, PhD, sales...), target years, remote on/off.

## Setup (5 minutes)

1. **Phone:** install the **ntfy** app (iOS / Android) and subscribe to a topic with a long random name, e.g. `radar-k3v9x2p7q1`. Anyone who knows the topic name can read your alerts, so treat it like a password.
2. **GitHub settings:** in your copy of this repo (fork it first), go to *Settings → Secrets and variables → Actions*:
   - Secret `NTFY_TOPIC`: your topic name
   - Secret `LOCATION`: your city, e.g. `Toronto, Canada`. Add the province/state if the name is common (`London, Canada`, `Cambridge, MA`).
   - Variable `LOCATION_RADIUS_KM` *(optional, default 50)*: how far you can commute. Every town of 15k+ people inside that distance counts as local, so you never have to list suburbs.
3. **First run:** *Actions → radar → Run workflow → sweep*. The first run sends one summary of every matching internship that's **already open**. After that, each new posting arrives as its own alert.

## Run locally

```bash
LOCATION="Toronto, Canada" LOCATION_RADIUS_KM=40 python -m radar.main sweep
```

The first line of output shows which towns count as local, so you can check the radius.

Without `NTFY_TOPIC` set, alerts are printed instead of sent. Needs only Python 3.11+, no packages.

## Good to know

- GitHub scheduled runs can start 5–20 minutes late when GitHub is busy. That's still far ahead of the job boards.
- GitHub pauses schedules in repos with no commits for 60 days. If you get that email, click *Enable workflow*.
- A company missing? See [`companies/README.md`](companies/README.md) to add it.
- A company that starts hiring near you gets picked up at the next sweep (within 6 hours), then polled every 10 minutes.

Company lists come from [Feashliaa/job-board-aggregator](https://github.com/Feashliaa/job-board-aggregator) (CC BY-NC 4.0). City data comes from [GeoNames](https://www.geonames.org/) (CC BY 4.0) and is rebuilt with `python scripts/build_cities.py`.
