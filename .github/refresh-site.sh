#!/bin/sh
# Tell the site the data changed: it marks its cached data stale and refreshes each
# page on its next visit (ajr-web: app/api/revalidate). Without the secret (a fork,
# or before it is set up) there is nothing to tell.
set -e
if [ -z "$REVALIDATE_SECRET" ]; then
  echo "::notice::REVALIDATE_SECRET is not set: the site refreshes on its own within a week"
  exit 0
fi
curl -fsS --retry 3 --retry-all-errors -X POST \
  -H "Authorization: Bearer $REVALIDATE_SECRET" \
  "${SITE_URL:-https://www.anotherjudorating.com}/api/revalidate"
echo
