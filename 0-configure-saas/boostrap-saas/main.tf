terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.100"
    }
    tfe = {
      source  = "hashicorp/tfe"
      version = "~> 0.83"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.28.0"
    }
  }
}
