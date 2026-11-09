# Another Judo Rating, backend infrastructure: the Supabase project, the Cloudflare
# Worker that starts the update workflow, and the ajr-backend repository on GitHub.
# One root module, one environment (production). The site's hosting (Render, DNS,
# Web Analytics, cache rules) is in ajr-web/infra.

terraform {
  required_version = "~> 1.14"

  required_providers {
    github     = { source = "integrations/github", version = "~> 6.13" }   # 6.13.0 (2026-07-08)
    supabase   = { source = "supabase/supabase", version = "~> 1.11" }     # 1.11.1 (2026-11-06)
    cloudflare = { source = "cloudflare/cloudflare", version = "~> 5.28" } # 5.28.1 (2026-10-20); v4 is in maintenance
  }

  # State in R2 (bucket ajr-terraform-state, ajr-backend/infra/r2.tf), read with its own
  # R2 API token (Object Read & Write on that bucket only): AWS_ACCESS_KEY_ID and
  # AWS_SECRET_ACCESS_KEY from ~/.config/ajr/terraform.env. The endpoint is given at init
  # (-backend-config="endpoints={s3=\"https://<account id>.r2.cloudflarestorage.com\"}"),
  # as a backend cannot read variables; README has the line. use_lockfile: a lock
  # object beside the state stops two applies at once.
  backend "s3" {
    bucket                      = "ajr-terraform-state"
    key                         = "backend/terraform.tfstate"
    region                      = "auto"
    use_lockfile                = true
    use_path_style              = true
    skip_credentials_validation = true
    skip_region_validation      = true
    skip_requesting_account_id  = true
    skip_metadata_api_check     = true
    skip_s3_checksum            = true
  }
}
