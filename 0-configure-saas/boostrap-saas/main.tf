terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.100"
    }
    tfe = {
      source  = "hashicorp/tfe"
      version = "~> 0.82"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.24.0"
    }
  }
}
