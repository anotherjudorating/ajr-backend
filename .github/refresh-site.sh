#!/bin/sh
# Tell the site the data changed: its cached data expires and each page is built anew
# on its next visit (ajr-web: app/api/revalidate). Then empty Cloudflare's cache of the
# site's pages (www only: data.<domain> keeps its own, every miss there is a billed R2
# read), which holds a page's HTML for hours (ajr-web/infra, the cache rules). Without
# a secret (a fork, or before it is set up) that part is skipped.
set -e
if [ -z "$REVALIDATE_SECRET" ]; then
  echo "::notice::REVALIDATE_SECRET is not set: the site refreshes on its own within a week"
else
  curl -fsS --retry 3 --retry-all-errors -X POST \
    -H "Authorization: Bearer $REVALIDATE_SECRET" \
    "${SITE_URL:-https://www.anotherjudorating.com}/api/revalidate"
  echo
fi
if [ -z "$CLOUDFLARE_PURGE_TOKEN" ] || [ -z "$CLOUDFLARE_ZONE_ID" ]; then
  echo "::notice::CLOUDFLARE_PURGE_TOKEN or CLOUDFLARE_ZONE_ID is not set: the edge keeps a page's HTML until it expires (3 hours)"
  exit 0
fi
# A failed purge does not fail the run (the data is published, the edge catches up
# within 3 hours): a warning in the run instead.
if ! curl -fsS --retry 3 --retry-all-errors -X POST \
  -H "Authorization: Bearer $CLOUDFLARE_PURGE_TOKEN" -H "Content-Type: application/json" \
  --data "{\"hosts\":[\"${SITE_HOST:-www.anotherjudorating.com}\"]}" \
  "https://api.cloudflare.com/client/v4/zones/$CLOUDFLARE_ZONE_ID/purge_cache"; then
  echo "::warning::Cloudflare's cache of the site was not purged: pages may lag the data by up to 3 hours"
fi
echo
