"""python -m ajr.rating [--full]"""

import argparse
import logging
import os

from ajr.core.job_run import job_run
from ajr.rating.job import run_rating


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Compute the rating.")
    parser.add_argument(
        "--full", action="store_true", help="from scratch, not only from what changed"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    with job_run("rating_full" if args.full else "rating"):
        outcome = run_rating(full=args.full)
    # For the update workflow: whether to tell the site to refresh its cache, and
    # whether a full run corrected the history (an issue is opened).
    if output := os.environ.get("GITHUB_OUTPUT"):
        with open(output, "a") as file:
            file.write(f"changed={'true' if outcome.changed else 'false'}\n")
            file.write(f"corrected={outcome.corrected}\n")


if __name__ == "__main__":
    main()
