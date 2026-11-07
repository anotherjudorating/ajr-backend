output "supabase_url" {
  value = "https://${supabase_project.main.id}.supabase.co"
}

output "database_url" {
  description = "What the DATABASE_URL secret holds (session pooler, IPv4)"
  value       = local.database_url
  sensitive   = true
}

output "supabase_publishable_key" {
  description = "The project's publishable (anon) key as the API reports it: the value ajr-web/infra must write into Render's SUPABASE_KEY"
  value       = data.supabase_apikeys.main.anon_key
  sensitive   = true
}

output "worker" {
  value = cloudflare_workers_script.update_trigger.script_name
}

output "ruleset_id" {
  value = github_repository_ruleset.main.ruleset_id
}
