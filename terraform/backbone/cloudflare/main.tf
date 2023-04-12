terraform {
  required_providers {
    cloudflare = {
      source = "cloudflare/cloudflare"
      version = ">= 3.14.0, < 5.0.0"
    }
  }
  required_version = ">= 1.1.8, < 2.0.0"
}

provider "cloudflare" {
  api_token = var.api_token
}