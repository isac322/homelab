terraform {
  required_providers {
    vultr = {
      source  = "vultr/vultr"
      version = "~> 2.27.1"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.12.0"
    }
  }
}
