terraform {
  required_version = "~> 1.13"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.100.0"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.12.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.1.0"
    }
  }

  cloud {
    organization = "bhyoo"

    workspaces {
      name = "homelab-backbone"
    }
  }
}

provider "cloudflare" {
  api_token = var.cloudflare_token_for_token_issuing
}
provider "aws" {
  region = "ap-northeast-2"

  default_tags {
    tags = {
      Owner               = "bhyoo"
      Project             = "homelab"
      terraform-base-path = "homelab/1-provision/env/backbone"
    }
  }
}

module "dns_secrets" {
  source = "./dns-secrets"

  k8s_cluster_name                            = "backbone"
  aws_iam_group_name_cf_origin_ca_cert_issuer = var.aws_iam_group_name_cf_origin_ca_cert_issuer
  use_democratic_csi                          = true

  providers = {
    aws        = aws
    cloudflare = cloudflare
    tls        = tls
  }
}
