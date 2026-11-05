# Update trigger

A Cloudflare Worker that starts the "Update data" workflow every 15 minutes, and
nightly (02:40 UTC) with `full_rating`, `records` and `check` (`worker.js`, schedules in
`wrangler.toml`). GitHub's own schedule fired only a few times a day; the Worker's
cron runs on time, on Cloudflare's free plan.

Deploy (from this folder, with a Cloudflare API token allowed "Account > Workers
Scripts > Edit" in `CLOUDFLARE_API_TOKEN`, and `CLOUDFLARE_ACCOUNT_ID`):

```bash
npx wrangler@4 deploy
npx wrangler@4 secret put GITHUB_TOKEN   # reads the token from the prompt or stdin
```

`GITHUB_TOKEN`: a fine-grained personal access token, resource owner
`anotherjudorating`, only the repository `ajr-backend`, repository permission
"Actions: Read and write". When it expires the runs stop: a failed dispatch shows
as a failed cron run in the Cloudflare dashboard (Workers > ajr-update-trigger >
Logs), and the site's "last update" stops moving. Renew it before it expires and
put the new one with `secret put`.
