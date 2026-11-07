terraform {
  required_providers {
    vultr = {
      source  = "vultr/vultr"
      version = "~> 2.33.2"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.28.0"
    }
  }
}
