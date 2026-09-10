# Company lists

One JSON array per applicant-tracking system. Greenhouse, Lever and Ashby entries are board slugs; Workday entries are `tenant|wdN|site`.

Source: [Feashliaa/job-board-aggregator](https://github.com/Feashliaa/job-board-aggregator) `data/*_companies.json`, licensed **CC BY-NC 4.0** (non-commercial use only). Harvested from Common Crawl, so many slugs are dead; the radar's sweep marks which ones are live.

To add a company yourself, find its careers page URL:

| URL looks like | Add to | Entry |
|---|---|---|
| `boards.greenhouse.io/acme` or `job-boards.greenhouse.io/acme` | `greenhouse.json` | `acme` |
| `jobs.lever.co/acme` | `lever.json` | `acme` |
| `jobs.ashbyhq.com/acme` | `ashby.json` | `acme` |
| `acme.wd5.myworkdayjobs.com/en-US/AcmeCareers` | `workday.json` | `acme\|wd5\|AcmeCareers` |
