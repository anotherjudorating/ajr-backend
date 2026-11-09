# Identifiers (not secrets; the defaults are production's, read on 2026-11-07).

variable "github_owner" {
  type    = string
  default = "anotherjudorating" # org id 348801882
}

variable "github_repository" {
  type    = string
  default = "ajr-backend" # repo id 1435677012
}

variable "supabase_project_ref" {
  type    = string
  default = "vrnpqahtpjrlmlrkzbja"
}

variable "supabase_organization_id" {
  description = "Organization slug: supabase.com/dashboard/org/<slug>"
  type        = string
  default     = "xhihsrgzeswkwkvceypf"
}

variable "cloudflare_account_id" {
  description = "Dashboard → any zone → Overview → API (right column) → Account ID"
  type        = string
}

variable "site_url" {
  type    = string
  default = "https://www.anotherjudorating.com"
}

# Provider tokens: TF_VAR_<name> exported from ~/.config/ajr/terraform.env (README),
# or terraform.tfvars (git-ignored). Minimal permissions in the README.

variable "github_token" {
  description = "Fine-grained PAT, owner anotherjudorating, repo ajr-backend (+ ajr-web if shared with ajr-web/infra): Administration RW, Secrets RW, Variables RW, Contents R, Metadata R"
  type        = string
  sensitive   = true
}

variable "supabase_access_token" {
  description = "supabase.com/dashboard/account/tokens: a read-write token (the read-only one in ~/.config/ajr/supabase.env cannot apply)"
  type        = string
  sensitive   = true
}

variable "cloudflare_api_token" {
  description = "Account › Workers Scripts › Edit (+ Account Settings › Read); zone permissions only if the same token also serves ajr-web/infra"
  type        = string
  sensitive   = true
}

# Values Terraform writes into other systems (secrets of the application).

variable "supabase_database_password" {
  description = "The database password (the one inside today's DATABASE_URL secret). The API never returns it: used to build DATABASE_URL and to satisfy supabase_project (ignore_changes). Never reset it: every workflow would lose its connection string."
  type        = string
  sensitive   = true
}

variable "revalidate_secret" {
  description = "Shared by ajr-web (/api/revalidate, Render env REVALIDATE_SECRET in ajr-web/infra) and the backend workflows (Actions secret REVALIDATE_SECRET). ~/.config/ajr/revalidate.env"
  type        = string
  sensitive   = true
}


variable "cloudflare_zone_id" {
  description = "Zone anotherjudorating.com: the R2 custom domain lives in it"
  type        = string
}

variable "domain" {
  description = "The site's domain; the R2 data is served at data.<domain>"
  type        = string
  default     = "anotherjudorating.com"
}

variable "r2_access_key_id" {
  description = "R2 API token 'ajr-data uploads' (Object Read & Write, bucket ajr-data): Access Key ID"
  type        = string
  sensitive   = true
}

variable "r2_secret_access_key" {
  description = "The same token's Secret Access Key"
  type        = string
  sensitive   = true
}
