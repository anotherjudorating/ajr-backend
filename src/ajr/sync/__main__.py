"""python -m ajr.sync [--full]"""

import argparse
import asyncio
import logging
import os

from ajr.core.job_run import job_run
from ajr.sync.job import run_sync


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Copy judobase into the database.")
    parser.add_argument(
        "--full", action="store_true", help="re-fetch contests of every competition"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    with job_run("sync_full" if args.full else "sync"):
        unannounced = asyncio.run(run_sync(full=args.full))
    # For the update workflow: competitions whose results changed unannounced (an
    # issue is opened: the 15-minute sync missed them until this full one).
    if output := os.environ.get("GITHUB_OUTPUT"):
        with open(output, "a") as file:
            file.write(f"unannounced={len(unannounced)}\n")
            names = "; ".join(f"{c.id} {c.name}" for c in unannounced)
            file.write(f"unannounced_names={names}\n")


if __name__ == "__main__":
    main()
