# GitHub: the ajr-backend repository, its ruleset on main, the Actions secrets the
# workflows read, security settings. ajr-web is managed from ajr-web/infra.
#
# Not here: org settings (github_organization_settings wants billing_email and owns
# ~30 fields; not worth it for one owner), CodeQL default setup (no resource in the
# provider), Dependabot version updates (.github/dependabot.yml is the configuration).

resource "github_repository" "backend" {
  name        = var.github_repository
  description = "Data sync and rating engine for Another Judo Rating."
  visibility  = "public"

  # As found 2026-11-07 (wiki and projects are on but unused: switching them off is a
  # later, deliberate change).
  has_issues      = true
  has_wiki        = true
  has_projects    = true
  has_discussions = false

  # Merge settings are not readable without Administration: read. Leave them unset:
  # the first plan after import shows the real values; copy them here, then they are
  # pinned. (Unset = "keep whatever the API has" for these arguments.)
  # allow_merge_commit     = true
  # allow_squash_merge     = true
  # allow_rebase_merge     = true
  # delete_branch_on_merge = true

  # Public repository: advanced_security cannot be set; secret scanning and push
  # protection can. If the first plan shows them "disabled" → "enabled", that is a
  # wanted change (audit 11-03).
  security_and_analysis {
    secret_scanning {
      status = "enabled"
    }
    secret_scanning_push_protection {
      status = "enabled"
    }
  }

  archive_on_destroy = true # never delete code through Terraform

  lifecycle {
    prevent_destroy = true
  }
}

resource "github_repository_dependabot_security_updates" "backend" {
  repository = github_repository.backend.name
  enabled    = true
}

# The ruleset on main: exists today (id 26053455) under the name "maun" (a typo);
# Terraform renames it. Required check: the "tests" job of tests.yml.
resource "github_repository_ruleset" "main" {
  name        = "main"
  repository  = github_repository.backend.name
  target      = "branch"
  enforcement = "active"

  conditions {
    ref_name {
      include = ["~DEFAULT_BRANCH"]
      exclude = []
    }
  }

  rules {
    deletion         = true
    non_fast_forward = true

    pull_request {
      required_approving_review_count   = 0
      dismiss_stale_reviews_on_push     = false
      require_code_owner_review         = false
      require_last_push_approval        = false
      required_review_thread_resolution = false
      allowed_merge_methods             = ["merge", "squash", "rebase"]
      # The API also returns require_extra_approval_for_unattributed_changes = true;
      # provider 6.13 has no such argument. If the plan shows a perpetual diff, pin
      # it with ignore_changes.
    }

    required_status_checks {
      strict_required_status_checks_policy = false
      do_not_enforce_on_create             = false
      required_check {
        context        = "tests"
        integration_id = 15368 # GitHub Actions
      }
    }
  }
}

# Actions secrets: the only two the workflows read (update.yml, release.yml,
# backup.yml: DATABASE_URL; update.yml, release.yml: REVALIDATE_SECRET).
#
# DATABASE_URL is built from the pooler's session-mode string in the README's
# format (session mode 5432, postgresql+psycopg://). Secret values are never
# readable: after the import the first apply rewrites both with the values given
# here, so check them (README, "Проверка") before applying.
data "supabase_pooler" "main" {
  project_ref = var.supabase_project_ref
}

locals {
  pooler_transaction_url = values(data.supabase_pooler.main.url)[0]
  database_url = replace(
    replace(
      replace(local.pooler_transaction_url, "[YOUR-PASSWORD]", var.supabase_database_password),
      ":6543/", ":5432/"
    ),
    "postgresql://", "postgresql+psycopg://"
  )
  # With ssl_enforcement = true (supabase.tf), in the same apply:
  # database_url = "${local.database_url}?sslmode=require"
}

resource "github_actions_secret" "database_url" {
  repository      = github_repository.backend.name
  secret_name     = "DATABASE_URL"
  plaintext_value = local.database_url
}

resource "github_actions_secret" "revalidate_secret" {
  repository      = github_repository.backend.name
  secret_name     = "REVALIDATE_SECRET"
  plaintext_value = var.revalidate_secret
}

# Which actions may run. The workflows use actions/*, astral-sh/setup-uv and docker
# images; "all" is assumed (not readable with the discovery token). Tightening to
# selected + sha pinning is a later change.
resource "github_actions_repository_permissions" "backend" {
  repository      = github_repository.backend.name
  enabled         = true
  allowed_actions = "all"
}
