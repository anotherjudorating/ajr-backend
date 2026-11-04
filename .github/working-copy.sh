#!/usr/bin/env bash
# The update job's working copy of production, in the Postgres container "db"
# (.github/workflows/update-copy.yml), kept between runs as one dump in $COPY.
#
#   restore <cache key>  the previous run's copy; without one (no cache key), a new
#                        copy: our migrations, then production's data (once in a
#                        while: it reads all of production), remembered as published
#   dump                 the copy as it is now, for the next run
set -e
case "$1" in
restore)
  if [ -n "$2" ]; then
    echo "The copy of $2"
    docker exec db pg_restore -U postgres -d postgres --no-owner --exit-on-error "/work/$COPY"
  else
    echo "No copy: a new one from production"
    uv run alembic upgrade head
    url="${PRODUCTION_DATABASE_URL/postgresql+psycopg:/postgresql:}"
    echo "::add-mask::$url"
    docker exec db pg_dump "$url" --format=custom --data-only --schema=ajr \
      --exclude-table=ajr.alembic_version --file=/work/production.dump
    docker exec db pg_restore -U postgres -d postgres --data-only --disable-triggers \
      --exit-on-error /work/production.dump
    rm production.dump
    uv run python -m ajr.publish adopt
  fi
  ;;
dump)
  docker exec db pg_dump -U postgres --format=custom --compress=zstd:3 \
    --file="/work/$COPY" postgres
  ls -lh "$COPY"
  ;;
*)
  echo "usage: $0 restore <cache key> | dump" >&2
  exit 2
  ;;
esac
