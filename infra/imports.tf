# Import blocks (Terraform >= 1.5): `terraform plan` shows "N to import" and the
# differences; `terraform apply` records them. Nothing is created here. Keep the file
# after the import (the blocks are no-ops once the objects are in the state) or
# delete it: both work.
#
# IDs read on 2026-11-07 with read-only tokens.

# ---- GitHub -------------------------------------------------------------------

import {
  to = github_repository.backend
  id = "ajr-backend"
}

import {
  to = github_repository_ruleset.main
  id = "ajr-backend:26053455" # named "maun" today; Terraform renames it to "main"
}

import {
  to = github_actions_secret.database_url
  id = "ajr-backend:DATABASE_URL" # the value is not readable: the first apply rewrites it
}

import {
  to = github_actions_secret.revalidate_secret
  id = "ajr-backend:REVALIDATE_SECRET"
}

import {
  to = github_repository_dependabot_security_updates.backend
  id = "ajr-backend"
}

import {
  to = github_actions_repository_permissions.backend
  id = "ajr-backend"
}

# ---- Supabase -----------------------------------------------------------------

import {
  to = supabase_project.main
  id = "vrnpqahtpjrlmlrkzbja"
}

import {
  to = supabase_settings.main
  id = "vrnpqahtpjrlmlrkzbja"
}

# ---- Cloudflare (account) -----------------------------------------------------

import {
  to = cloudflare_workers_script.update_trigger
  id = "${var.cloudflare_account_id}/ajr-update-trigger"
}

import {
  to = cloudflare_workers_cron_trigger.update_trigger
  id = "${var.cloudflare_account_id}/ajr-update-trigger"
}

import {
  to = cloudflare_workers_script_subdomain.update_trigger
  id = "${var.cloudflare_account_id}/ajr-update-trigger"
}
