#!/usr/bin/env bash
# The update job's working copy of production, in the Postgres container "db"
# (.github/workflows/update.yml), kept between runs as one dump in $COPY.
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
    # the rows some migrations seed (ajr.tables_export's) would clash with production's
    docker exec db psql -U postgres -v ON_ERROR_STOP=1 -q -c "do \$\$ declare t text; begin
      select string_agg(format('%I.%I', schemaname, tablename), ', ') into t
      from pg_tables where schemaname = 'ajr' and tablename <> 'alembic_version';
      execute 'truncate ' || t; end \$\$"
    url="${PRODUCTION_DATABASE_URL/postgresql+psycopg:/postgresql:}"
    echo "::add-mask::$url"
    docker exec db pg_dump "$url" --format=custom --data-only --schema=ajr \
      --exclude-table=ajr.alembic_version --file=/work/production.dump
    docker exec db pg_restore -U postgres -d postgres --data-only --disable-triggers \
      --exit-on-error /work/production.dump
    rm production.dump
    # production's sequences never moved (its rows come from the publish): each one
    # after its table's highest id, or the next insert takes a used one
    docker exec db psql -U postgres -v ON_ERROR_STOP=1 -q -c "do \$\$ declare r record; begin
      for r in select s.relname as seq, t.relname as tab, a.attname as col
               from pg_class s
               join pg_depend d on d.objid = s.oid and d.deptype in ('a', 'i')
               join pg_class t on t.oid = d.refobjid
               join pg_attribute a on a.attrelid = t.oid and a.attnum = d.refobjsubid
               join pg_namespace n on n.oid = s.relnamespace
               where s.relkind = 'S' and n.nspname = 'ajr' loop
        execute format('select setval(%L, coalesce((select max(%I) from ajr.%I), 0) + 1, false)',
                       'ajr.' || r.seq, r.col, r.tab);
      end loop; end \$\$"
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
