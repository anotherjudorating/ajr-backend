output "project_ref" {
  value = supabase_project.ajr.id
}

output "database_password" {
  value     = random_password.db.result
  sensitive = true
}

output "pooler_urls" {
  description = "Pooler connection strings by mode. The password is a [YOUR-PASSWORD] placeholder."
  value       = data.supabase_pooler.ajr.url
  sensitive   = true
}
