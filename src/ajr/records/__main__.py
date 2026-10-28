"""python -m ajr.records"""

import logging

from ajr.core.job_run import job_run
from ajr.records.job import run_records


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    with job_run("records"):
        run_records()


if __name__ == "__main__":
    main()
