"""python -m ajr.rating"""

import logging

from ajr.core.job_run import job_run
from ajr.rating.job import run_rating


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    with job_run("rating"):
        run_rating()


if __name__ == "__main__":
    main()
