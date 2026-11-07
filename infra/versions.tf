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

  # Local state, git-ignored (*.tfstate*). One operator, one machine, applies only
  # by hand: a remote backend would add a bucket, a token and a lock to maintain
  # for nothing. The state holds secrets (the database password, DATABASE_URL,
  # REVALIDATE_SECRET), so it is kept outside the repository:
  #   terraform init -backend-config="path=$HOME/.config/ajr/tfstate/ajr-backend.tfstate"
  # and backed up with `terraform state pull` before each apply (README). Moving
  # to R2 (S3 backend) or HCP Terraform later is `terraform init -migrate-state`.
  backend "local" {}
}
