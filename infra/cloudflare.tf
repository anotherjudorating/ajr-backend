# Cloudflare: the Worker that starts the "Update data" workflow on schedule
# (cloudflare/worker.js, schedules of cloudflare/wrangler.toml). Account-level only;
# the zone (DNS, cache rules, Web Analytics) is in ajr-web/infra.
#
# Terraform replaces `wrangler deploy`; wrangler.toml stays for `wrangler dev`.
# A Terraform upload replaces every binding it does not list: keep_bindings keeps the
# GITHUB_TOKEN secret put with `wrangler secret put`, so the token stays out of the
# state and is rotated with wrangler as before (cloudflare/README.md). To manage it
# here instead: drop keep_bindings, add a sensitive variable and the binding
#   { name = "GITHUB_TOKEN", type = "secret_text", text = var.github_dispatch_token }
# (the token then lives in the state).

locals {
  worker_file = "${path.module}/../cloudflare/worker.js"
}

resource "cloudflare_workers_script" "update_trigger" {
  account_id         = var.cloudflare_account_id
  script_name        = "ajr-update-trigger"
  content_file       = local.worker_file
  content_sha256     = filesha256(local.worker_file)
  main_module        = "worker.js"
  compatibility_date = "2026-10-01" # wrangler.toml

  bindings = [
    { name = "GITHUB_REPO", type = "plain_text", text = "${var.github_owner}/${var.github_repository}" },
  ]
  keep_bindings = ["secret_text"]
}

resource "cloudflare_workers_cron_trigger" "update_trigger" {
  account_id  = var.cloudflare_account_id
  script_name = cloudflare_workers_script.update_trigger.script_name
  schedules = [
    { cron = "*/15 * * * *" }, # every 15 minutes
    { cron = "40 2 * * *" },   # nightly: full_rating + records
    { cron = "10 3 * * 1" },   # Monday nights: full + check
  ]
}

# workers_dev = false in wrangler.toml: no public URL for the Worker.
resource "cloudflare_workers_script_subdomain" "update_trigger" {
  account_id  = var.cloudflare_account_id
  script_name = cloudflare_workers_script.update_trigger.script_name
  enabled     = false
}
