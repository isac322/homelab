terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.100.0"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.12.0"
    }
    postmark = {
      source  = "jcf/postmark"
      version = "1.2.2"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.1.0"
    }
  }
}
