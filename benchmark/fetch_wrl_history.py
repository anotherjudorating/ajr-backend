"""Every athlete's IJF World Ranking List history from judobase (competitor.wrl_history):
one row per athlete, weekly list and weight, into data/wrl_history.csv.gz. judobase
keeps about the last year and a half (from 2025 week 12 when fetched on 2026-11-11);
the seniors', juniors' and cadets' lists. Resumable: the athletes already fetched are
in data/wrl_done.txt, their raw rows in data/wrl_raw.jsonl (neither in git).

    DATABASE_URL=… uv run python fetch_wrl_history.py     # the athletes: ajr.athlete
"""

import asyncio
import csv
import gzip
import json
import os
import time

import psycopg
from judobase import JudoBase
from sqlalchemy import make_url

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(OUT, exist_ok=True)
done_path = f"{OUT}/wrl_done.txt"
raw_path = f"{OUT}/wrl_raw.jsonl"
done = set(open(done_path).read().split()) if os.path.exists(done_path) else set()
url = (
    make_url(os.environ["DATABASE_URL"])
    .set(drivername="postgresql")
    .render_as_string(hide_password=False)
)
with psycopg.connect(url) as c:
    ids = [str(r[0]) for r in c.execute("select id from ajr.athlete order by id")]
todo = [i for i in ids if i not in done]
print(f"athletes {len(ids)}, to fetch {len(todo)}", flush=True)


async def main():
    sem = asyncio.Semaphore(8)
    raw = open(raw_path, "a")
    dn = open(done_path, "a")
    count = {"ok": 0, "rows": 0, "err": 0}
    start = time.time()
    async with JudoBase() as api:

        async def one(jid):
            async with sem:
                for attempt in range(4):
                    try:
                        rows = await api.rating_history_by_id(jid)
                        break
                    except Exception as e:
                        if attempt == 3:
                            count["err"] += 1
                            print("error", jid, repr(e)[:120], flush=True)
                            return
                        await asyncio.sleep(2 * (attempt + 1))
                for r in rows:
                    raw.write(json.dumps({"athlete_id": int(jid), **r.model_dump()}) + "\n")
                dn.write(jid + "\n")
                count["ok"] += 1
                count["rows"] += len(rows)
                if count["ok"] % 500 == 0:
                    raw.flush()
                    dn.flush()
                    print(
                        f"{count['ok']}/{len(todo)} rows {count['rows']}"
                        f" errors {count['err']} {time.time() - start:.0f}s",
                        flush=True,
                    )

        await asyncio.gather(*(one(j) for j in todo))
    raw.close()
    dn.close()
    print("fetched", count, flush=True)


asyncio.run(main())

# the archive: one CSV, the week parsed from the version label
with open(raw_path) as f, gzip.open(f"{OUT}/wrl_history.csv.gz", "wt", newline="") as out:
    w = csv.writer(out)
    w.writerow(["athlete_id", "version", "year", "week", "age", "weight", "place", "points"])
    n = 0
    for line in f:
        r = json.loads(line)
        parts = r["version"].rsplit("_", 2)
        year, week = (parts[-2], parts[-1]) if len(parts) == 3 else ("", "")
        w.writerow(
            [
                r["athlete_id"],
                r["version"],
                year,
                week,
                r["age"],
                r["weight"],
                r["place"],
                r["points"],
            ]
        )
        n += 1
print("archive rows", n, flush=True)
