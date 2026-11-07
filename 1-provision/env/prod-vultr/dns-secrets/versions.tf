terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.100.0"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.28.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.4.0"
    }
  }
}
