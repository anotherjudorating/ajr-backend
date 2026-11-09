provider "github" {
  owner = var.github_owner
  token = var.github_token
}

provider "supabase" {
  access_token = var.supabase_access_token
}

provider "cloudflare" {
  api_token = var.cloudflare_api_token
}
