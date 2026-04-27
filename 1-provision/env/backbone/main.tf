terraform {
  required_version = "~> 1.13"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.100.0"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.19.0"
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
  cloudflare_account_id                       = var.cloudflare_account_id
  aws_iam_group_name_cf_origin_ca_cert_issuer = var.aws_iam_group_name_cf_origin_ca_cert_issuer
  use_democratic_csi                          = true
  hindsight_openai_api_key                    = var.hindsight_openai_api_key
  hindsight_gcp_sa_key                        = var.hindsight_gcp_sa_key

  providers = {
    aws        = aws
    cloudflare = cloudflare
    tls        = tls
  }
}
