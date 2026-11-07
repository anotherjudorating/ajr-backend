# Supabase: the project and its platform settings. Everything inside the database
# (schemas, api.* functions, grants, role statement_timeouts) stays in Alembic.
# Settings below are the values read on 2026-11-07 (Management API, read-only), so
# the first plan after import should show no change here.

resource "supabase_project" "main" {
  organization_id   = var.supabase_organization_id
  name              = "ajr"
  region            = "eu-central-1"
  database_password = var.supabase_database_password
  # instance_size: the free plan's Nano. If the first plan proposes to change it, add
  # it to ignore_changes rather than set it (a compute add-on is paid).

  lifecycle {
    prevent_destroy = true # a destroy here is the whole database
    # The API never returns the password; a different value here would not rotate it.
    ignore_changes = [database_password, instance_size]
  }
}

resource "supabase_settings" "main" {
  project_ref = supabase_project.main.id

  # Data API (PostgREST): GET /v1/projects/{ref}/postgrest.
  api = jsonencode({
    db_schema            = "api"
    db_extra_search_path = "public,extensions"
    max_rows             = 1000
  })

  # Postgres parameters set through the platform: GET /v1/projects/{ref}/config/database/postgres
  # returns only the overrides, today exactly one (set by the CLI on 2026-11-05).
  # A change of shared_buffers restarts Postgres: apply such changes between runs of
  # update.yml (the Worker fires every 15 minutes). statement_timeout here would be
  # the server default for every role; the 3 s of anon and 8 s of authenticated are
  # role settings, i.e. a migration, not this block.
  database = jsonencode({
    shared_buffers = "64MB"
  })

  # Network restrictions: open, as found (GitHub runners and Render have no fixed IPs).
  network = jsonencode({
    restrictions = ["0.0.0.0/0", "::/0"]
  })

  # Found: false. Switch to true in the same apply as DATABASE_URL?sslmode=require
  # (github.tf): audit 11-03, M1.
  ssl_enforcement = false

  # Not managed, deliberately: auth (the site has no users; defaults), pooler
  # (defaults), storage (unused).
}

# The site's publishable key is read, not managed: compare the output with what
# ajr-web/infra writes into Render's SUPABASE_KEY.
data "supabase_apikeys" "main" {
  project_ref = supabase_project.main.id
}
