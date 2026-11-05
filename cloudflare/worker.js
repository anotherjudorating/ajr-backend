// Starts the "Update data" workflow (.github/workflows/update.yml) on schedule:
// GitHub's own schedule fired only a few times a day. The schedules are in
// wrangler.toml; deploy: see cloudflare/README.md.
// GITHUB_TOKEN (a secret): fine-grained token for the repository only, "Actions: Read and write".

// What each schedule asks the run to do (the workflow's inputs).
const RUNS = {
  "*/15 * * * *": {},
  // nightly: the rating from scratch, the records, every table compared with production
  // (not `full`: that re-fetches every competition from judobase too)
  "40 2 * * *": { full_rating: "true", records: "true", check: "true" },
};

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(dispatch(env, RUNS[event.cron] ?? {}));
  },
};

async function dispatch(env, inputs) {
  const url = `https://api.github.com/repos/${env.GITHUB_REPO}/actions/workflows/update.yml/dispatches`;
  const res = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "ajr-update-trigger",
    },
    body: JSON.stringify({ ref: "main", inputs }),
  });
  // Throwing marks the cron run as failed in the Cloudflare dashboard.
  if (res.status !== 204) {
    throw new Error(`GitHub dispatch failed: ${res.status} ${await res.text()}`);
  }
}
