# ajr-backend

Data sync and rating engine for Another Judo Rating.

There is no API server: a scheduled job fills a Supabase Postgres database, and the
site reads it through the Supabase Data API, which exposes only the `api` schema
(functions in the "api for the site" migration).

## What runs

| Workflow | When | Steps |
|---|---|---|
| `update.yml` | every 15 minutes; nightly with a full rating; or by hand (optionally all from scratch) | `alembic upgrade head` → `python -m ajr.sync` → `python -m ajr.rating` |
| `backup.yml` | Mondays | dump of `country`, `competition`, `athlete`, `contest` as a workflow artifact, kept 90 days |
| `tests.yml` | pull requests, pushes to `main` | ruff, pytest against Postgres 17 |

Both data workflows need the repository secret `DATABASE_URL`
(`postgresql+psycopg://user:password@host:port/postgres`). Every step records itself
in `ajr.job_run` (type, status, start and end, traceback of a failure).

- **sync** copies judobase: competitions happening now or in the next two weeks
  (draws, live results) and past competitions that changed. `--full` re-fetches all.
- **rating** recomputes Glicko-2 from the first competition whose results changed
  since the last run (the sync marks it), or from scratch with `--full`; why and how:
  `src/ajr/rating/job.py`. Parameters and how they were chosen:
  `src/ajr/rating/tune.py` and `tune_ranking.py`.

## Local development

```bash
uv sync
echo 'DATABASE_URL=postgresql+psycopg://...' > .env   # the database to work with
uv run pytest           # starts a throwaway local Postgres; never touches .env's database
uv run python -m ajr.sync
uv run python -m ajr.rating
uv run python -m ajr.rating.tune --check 10   # parameter search on the real data
```

Tests need `initdb`/`pg_ctl` on the PATH (e.g. `brew install postgresql`) or a
`TEST_DATABASE_URL` pointing to a local database.

## Restoring from a backup

Everything except the judobase copy is rebuilt from it, so a restore is:

1. Download the artifact of a "Backup" run and unzip it: `ajr-YYYY-MM-DD.dump`.
2. Create the tables in the (empty) database: `uv run alembic upgrade head`.
3. Load the data with `pg_restore` 17 (the URL without `+psycopg`):
   ```bash
   pg_restore --data-only --no-owner --dbname "postgresql://..." ajr-YYYY-MM-DD.dump
   ```
4. Rebuild the rating: `uv run python -m ajr.rating`.

## Infrastructure

`infra/` holds the Supabase project in Terraform. The state file and variables are
not in git; `infra/.env` holds `SUPABASE_ACCESS_TOKEN`.
