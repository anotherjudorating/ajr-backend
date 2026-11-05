"""python -m ajr.publish adopt | publish [--dry-run] | check

The working copy is DATABASE_URL's database (where the jobs ran), production is
PRODUCTION_DATABASE_URL's. In GitHub Actions, the changes are listed in the run's
summary, and `publish` writes changed=true|false for the step that refreshes the site.
"""

import argparse
import logging
import os
import sys

import psycopg
from sqlalchemy import make_url

from ajr.publish import adopt, check, publish, site_changed


def plain(url: str) -> str:
    """psycopg's own URL (no SQLAlchemy driver name)."""
    return make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)


def summary(lines: list[str]) -> None:
    if path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(path, "a") as file:
            file.write("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Publish the working copy to production.")
    parser.add_argument("command", choices=["adopt", "publish", "check"])
    parser.add_argument("--dry-run", action="store_true", help="publish, then roll back")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    with psycopg.connect(plain(os.environ["DATABASE_URL"])) as local:
        if args.command == "adopt":
            adopt(local)
            return 0
        with psycopg.connect(plain(os.environ["PRODUCTION_DATABASE_URL"])) as remote:
            if args.command == "check":
                differences = check(local, remote)
                summary(
                    ["### Working copy vs production", ""]
                    + (
                        ["| table | rows here | rows in production |", "|---|---|---|"]
                        + [f"| {d.table} | {d.local_rows} | {d.remote_rows} |" for d in differences]
                        if differences
                        else ["Every published table is the same."]
                    )
                )
                return 1 if differences else 0

            published = publish(local, remote, args.dry_run)
            changes = [c for c in published if c.upserted or c.deleted]
    summary(
        [f"### {'Would publish (dry run)' if args.dry_run else 'Published'}", ""]
        + (
            ["| table | upserted | deleted |", "|---|---|---|"]
            + [
                f"| {c.table}{' (whole)' if c.whole else ''} | {c.upserted} | {c.deleted} |"
                for c in changes
            ]
            if changes
            else ["Nothing changed."]
        )
    )
    if output := os.environ.get("GITHUB_OUTPUT"):
        with open(output, "a") as file:
            refresh = site_changed(published) and not args.dry_run
            file.write(f"changed={'true' if refresh else 'false'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
