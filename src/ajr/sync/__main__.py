"""python -m ajr.sync [--full]"""

import argparse
import asyncio
import logging

from ajr.sync.job import run_sync

parser = argparse.ArgumentParser(description="Copy judobase into the database.")
parser.add_argument("--full", action="store_true", help="re-fetch contests of every competition")
args = parser.parse_args()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
asyncio.run(run_sync(full=args.full))
