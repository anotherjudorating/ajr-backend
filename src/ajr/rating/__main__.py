"""python -m ajr.rating [--full]"""

import argparse
import logging

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
        run_rating(full=args.full)


if __name__ == "__main__":
    main()
