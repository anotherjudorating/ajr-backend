#!/bin/sh
# The load test's database with nothing in its caches: Postgres restarted, the
# kernel's page cache dropped; then wait until PostgREST answers again.
set -e
docker restart db >/dev/null
sync
sudo sh -c 'echo 3 > /proc/sys/vm/drop_caches'
# over TCP: not the image's temporary server of its first start (socket only)
until docker exec db pg_isready -h 127.0.0.1 -U postgres >/dev/null; do sleep 1; done
until curl -sf -X POST "$API/rpc/last_update" -H 'Content-Type: application/json' -d '{}' >/dev/null; do sleep 1; done
