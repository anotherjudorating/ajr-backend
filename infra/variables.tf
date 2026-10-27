variable "supabase_organization_id" {
  description = "Supabase organization slug (from the dashboard URL)."
  type        = string
}

variable "supabase_region" {
  description = "Supabase region. Keep close to the Cloud Run region (europe-west3)."
  type        = string
  default     = "eu-central-1"
}

variable "project_name" {
  description = "Supabase project name."
  type        = string
  default     = "ajr"
}
