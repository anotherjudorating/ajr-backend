# ---- R2: past days' ranking tables and the open-data archive -----------------------
# docs/audits/2026-11-08-r2-tables-plan.md. The update job writes the files
# (ajr.tables); the site and anyone read them at data.<domain> through the
# Cloudflare edge (cache, WAF and rate-limit rules: ajr-web/infra). The Worker's kill
# switch sets the custom domain's `enabled` to false above 80 % of the free tier;
# `terraform apply` turns it back on (so no ignore_changes on `enabled`).

resource "cloudflare_r2_bucket" "data" {
  account_id    = var.cloudflare_account_id
  name          = "ajr-data"
  location      = "WEUR" # Western Europe: Render and Supabase are in Frankfurt
  storage_class = "Standard"
}

resource "cloudflare_r2_custom_domain" "data" {
  account_id  = var.cloudflare_account_id
  bucket_name = cloudflare_r2_bucket.data.name
  domain      = "data.${var.domain}"
  zone_id     = var.cloudflare_zone_id
  enabled     = true
  min_tls     = "1.2"
}

# r2.dev off: the custom domain, behind the zone's rules, is the only public way in.
resource "cloudflare_r2_managed_domain" "data" {
  account_id  = var.cloudflare_account_id
  bucket_name = cloudflare_r2_bucket.data.name
  enabled     = false
}

# Uploads interrupted halfway are cleaned up after a day.
resource "cloudflare_r2_bucket_lifecycle" "data" {
  account_id  = var.cloudflare_account_id
  bucket_name = cloudflare_r2_bucket.data.name
  rules = [{
    id         = "abort-multipart"
    enabled    = true
    conditions = { prefix = "" }
    abort_multipart_uploads_transition = {
      condition = { type = "Age", max_age = 86400 }
    }
  }]
}

# The update job uploads the files with these (ajr.tables): an R2 API token limited to
# Object Read & Write on ajr-data, made in the dashboard (R2 → Manage API tokens).
resource "github_actions_secret" "r2_access_key_id" {
  repository      = github_repository.backend.name
  secret_name     = "R2_ACCESS_KEY_ID"
  plaintext_value = var.r2_access_key_id
}

resource "github_actions_secret" "r2_secret_access_key" {
  repository      = github_repository.backend.name
  secret_name     = "R2_SECRET_ACCESS_KEY"
  plaintext_value = var.r2_secret_access_key
}

resource "github_actions_variable" "r2_account_id" {
  repository    = github_repository.backend.name
  variable_name = "R2_ACCOUNT_ID"
  value         = var.cloudflare_account_id
}

resource "github_actions_variable" "r2_bucket" {
  repository    = github_repository.backend.name
  variable_name = "R2_BUCKET"
  value         = cloudflare_r2_bucket.data.name
}

# Terraform's own state for both roots (ajr-backend/infra and ajr-web/infra): it holds
# secrets, so the bucket is private and read with its own R2 API token (Object Read &
# Write on this bucket only), never the update job's.
resource "cloudflare_r2_bucket" "terraform_state" {
  account_id    = var.cloudflare_account_id
  name          = "ajr-terraform-state"
  location      = "WEUR"
  storage_class = "Standard"
}
