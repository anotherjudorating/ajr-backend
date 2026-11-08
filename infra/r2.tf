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
