terraform {
  required_providers {
    vultr = {
      source  = "vultr/vultr"
      version = ">= 2.11.1, < 3.0.0"
    }
  }
  required_version = ">= 1.1.8, < 2.0.0"
}

provider "vultr" {
  api_key = var.api_key
}