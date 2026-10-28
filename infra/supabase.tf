resource "random_password" "db" {
  length  = 32
  special = false
}

resource "supabase_project" "ajr" {
  organization_id   = var.supabase_organization_id
  name              = var.project_name
  database_password = random_password.db.result
  region            = var.supabase_region

  lifecycle {
    # A change to name/region/org would plan a replacement: deleting the database.
    prevent_destroy = true
    # The API does not return the password; changing it here does not rotate it.
    ignore_changes = [database_password]
  }
}

resource "supabase_settings" "ajr" {
  project_ref     = supabase_project.ajr.id
  ssl_enforcement = true

  # The Data API serves only the `api` schema (functions for the site); `public`
  # and our `ajr` tables are not reachable with the publishable key.
  api = jsonencode({
    db_schema            = "api"
    db_extra_search_path = "public, extensions"
    max_rows             = 1000 # the largest weight category has ~650 active athletes
  })
}

data "supabase_pooler" "ajr" {
  project_ref = supabase_project.ajr.id
}
