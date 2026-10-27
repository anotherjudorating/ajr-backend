terraform {
  required_version = ">= 1.9"

  required_providers {
    supabase = {
      source  = "supabase/supabase"
      version = "~> 1.11"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # Local state for now. Move to a GCS backend once the GCP project exists:
  # state holds the database password.
}

# Reads the personal access token from SUPABASE_ACCESS_TOKEN.
provider "supabase" {}
