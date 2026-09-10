-- befirst jobs schema: written by the engine (radar/ingest.py), read by the web app.
-- Safe to run on every start. Keep semicolons out of comments (the loader splits on them).

CREATE SCHEMA IF NOT EXISTS jobs;

CREATE TABLE IF NOT EXISTS jobs.cities (
  id          integer PRIMARY KEY,             -- GeoNames id
  name        text NOT NULL,
  state       text NOT NULL,                   -- two-letter code
  lat         double precision NOT NULL,
  lon         double precision NOT NULL,
  population  integer NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs.postings (
  uid           text PRIMARY KEY,              -- source:board:external id
  source        text NOT NULL,                 -- greenhouse, lever, ashby, workday
  board         text NOT NULL,                 -- source:board, e.g. greenhouse:stripe
  company       text NOT NULL,
  title         text NOT NULL,
  url           text NOT NULL,
  job_type      text NOT NULL CHECK (job_type IN ('internship', 'part_time', 'full_time', 'other')),
  is_remote     boolean NOT NULL DEFAULT false,
  locations     text[] NOT NULL DEFAULT '{}',
  posted_at     timestamptz NOT NULL,          -- best estimate of when it went live
  first_seen_at timestamptz NOT NULL DEFAULT now(),
  search        tsvector GENERATED ALWAYS AS (to_tsvector('english', title || ' ' || company)) STORED
);

CREATE INDEX IF NOT EXISTS postings_posted_at ON jobs.postings (posted_at DESC);
CREATE INDEX IF NOT EXISTS postings_type_posted_at ON jobs.postings (job_type, posted_at DESC);
CREATE INDEX IF NOT EXISTS postings_board ON jobs.postings (board);
CREATE INDEX IF NOT EXISTS postings_search ON jobs.postings USING gin (search);

CREATE TABLE IF NOT EXISTS jobs.posting_cities (
  uid      text NOT NULL REFERENCES jobs.postings (uid) ON DELETE CASCADE,
  city_id  integer NOT NULL REFERENCES jobs.cities (id),
  PRIMARY KEY (uid, city_id)
);

CREATE INDEX IF NOT EXISTS posting_cities_city ON jobs.posting_cities (city_id);
