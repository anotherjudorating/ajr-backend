"""python -m ajr.sync [--full]"""

import argparse
import asyncio
import logging

from ajr.core.job_run import job_run
from ajr.sync.job import run_sync

parser = argparse.ArgumentParser(description="Copy judobase into the database.")
parser.add_argument("--full", action="store_true", help="re-fetch contests of every competition")
args = parser.parse_args()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
with job_run("sync_full" if args.full else "sync"):
    asyncio.run(run_sync(full=args.full))
