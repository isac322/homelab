terraform {
  required_providers {
    vultr = {
      source  = "vultr/vultr"
      version = "~> 2.17"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 4.20"
    }
  }
}
