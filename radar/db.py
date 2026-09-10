"""Postgres (Neon) access for the befirst jobs schema. Writes only rows that changed, to keep the free tier's compute low."""

from collections import defaultdict
from pathlib import Path

import psycopg

from .geo import City

SCHEMA = Path(__file__).resolve().parent.parent / "db" / "schema.sql"


def connect(url: str) -> psycopg.Connection:
    return psycopg.connect(url)


def ensure_schema(conn: psycopg.Connection, cities: list[City]) -> None:
    with conn.cursor() as cur:
        for statement in SCHEMA.read_text(encoding="utf-8").split(";"):
            body = "\n".join(l for l in statement.splitlines() if not l.strip().startswith("--"))
            if body.strip():
                cur.execute(body)
        cur.execute("SELECT count(*) FROM jobs.cities")
        if cur.fetchone()[0] == 0:
            with cur.copy("COPY jobs.cities (id, name, state, lat, lon, population) FROM STDIN") as cp:
                for c in cities:
                    cp.write_row((c.gid, c.name, c.admin1, c.lat, c.lon, c.pop))
    conn.commit()


def hot_boards(conn: psycopg.Connection, days: int) -> dict[str, list[str]]:
    """Boards with a posting in the last few days: the ones most likely to post again soon."""
    boards: dict[str, list[str]] = defaultdict(list)
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT board FROM jobs.postings WHERE posted_at > now() - make_interval(days => %s)", (days,))
        for (key,) in cur:
            source, _, board = key.partition(":")
            boards[source].append(board)
    return dict(boards)


def existing_uids(conn: psycopg.Connection, boards: list[str]) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT uid FROM jobs.postings WHERE board = ANY(%s)", (boards,))
        return {uid for (uid,) in cur}


def write(conn: psycopg.Connection, rows: list[tuple], present: set[str], boards: list[str], max_age_days: int) -> dict:
    """rows: (uid, source, board, company, title, url, job_type, is_remote, locations, posted_at, city_ids).
    present: every uid still listed on the fetched boards (a superset of rows). Anything else on those boards was taken down."""
    with conn.cursor() as cur:
        cur.execute("""CREATE TEMP TABLE incoming (uid text, source text, board text, company text, title text, url text,
                       job_type text, is_remote boolean, locations text[], posted_at timestamptz, city_ids integer[]) ON COMMIT DROP""")
        cur.execute("CREATE TEMP TABLE present (uid text PRIMARY KEY) ON COMMIT DROP")
        cur.execute("CREATE TEMP TABLE fetched_boards (board text PRIMARY KEY) ON COMMIT DROP")
        cur.execute("CREATE TEMP TABLE changed (uid text PRIMARY KEY, inserted boolean) ON COMMIT DROP")
        with cur.copy("COPY incoming FROM STDIN") as cp:
            cp.set_types(["text"] * 7 + ["bool", "text[]", "timestamptz", "int4[]"])
            for row in rows:
                cp.write_row(row)
        with cur.copy("COPY present FROM STDIN") as cp:
            for uid in present:
                cp.write_row((uid,))
        with cur.copy("COPY fetched_boards FROM STDIN") as cp:
            for board in set(boards):
                cp.write_row((board,))

        cur.execute("""
            WITH up AS (
              INSERT INTO jobs.postings AS p (uid, source, board, company, title, url, job_type, is_remote, locations, posted_at)
              SELECT uid, source, board, company, title, url, job_type, is_remote, locations, posted_at FROM incoming
              ON CONFLICT (uid) DO UPDATE
                SET company = EXCLUDED.company, title = EXCLUDED.title, url = EXCLUDED.url,
                    job_type = EXCLUDED.job_type, is_remote = EXCLUDED.is_remote, locations = EXCLUDED.locations
                WHERE (p.company, p.title, p.url, p.job_type, p.is_remote, p.locations)
                      IS DISTINCT FROM (EXCLUDED.company, EXCLUDED.title, EXCLUDED.url, EXCLUDED.job_type, EXCLUDED.is_remote, EXCLUDED.locations)
              RETURNING p.uid, (p.xmax = 0)
            )
            INSERT INTO changed SELECT * FROM up""")
        cur.execute("SELECT count(*) FILTER (WHERE inserted), count(*) FILTER (WHERE NOT inserted) FROM changed")
        inserted, updated = cur.fetchone()

        cur.execute("DELETE FROM jobs.posting_cities pc USING changed ch WHERE pc.uid = ch.uid")
        cur.execute("""
            INSERT INTO jobs.posting_cities (uid, city_id)
            SELECT DISTINCT i.uid, u.city_id
            FROM incoming i JOIN changed ch ON ch.uid = i.uid
            CROSS JOIN LATERAL unnest(i.city_ids) AS u(city_id)
            WHERE EXISTS (SELECT 1 FROM jobs.cities c WHERE c.id = u.city_id)""")

        cur.execute("""DELETE FROM jobs.postings p USING fetched_boards fb
                       WHERE p.board = fb.board AND NOT EXISTS (SELECT 1 FROM present pr WHERE pr.uid = p.uid)""")
        removed = cur.rowcount
        cur.execute("DELETE FROM jobs.postings WHERE posted_at < now() - make_interval(days => %s)", (max_age_days,))
        expired = cur.rowcount
        cur.execute("SELECT count(*) FROM jobs.postings")
        total = cur.fetchone()[0]
    conn.commit()
    return {"new": inserted, "updated": updated, "taken down": removed, "expired": expired, "total in db": total}
