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
    postmark = {
      source  = "jcf/postmark"
      version = "1.2.2"
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
provider "postmark" {
  account_token = var.postmark_account_token
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
  cloudflare_main_zone_id                     = var.cloudflare_main_zone_id
  aws_iam_group_name_cf_origin_ca_cert_issuer = var.aws_iam_group_name_cf_origin_ca_cert_issuer
  use_democratic_csi                          = true
  hindsight_openai_embeddings_api_key         = var.hindsight_openai_embeddings_api_key
  hindsight_gcp_vertex_ai_sa_key              = var.hindsight_gcp_vertex_ai_sa_key
  hindsight_gemini_api_key                    = var.hindsight_gemini_api_key
  hermes_openai_proxy                         = var.hermes_openai_proxy
  hermes_gemini_api_key                       = var.hermes_gemini_api_key
  hermes_isacmes_telegram_token               = var.hermes_isacmes_telegram_token
  hermes_isacmes_jay_telegram_token           = var.hermes_isacmes_jay_telegram_token

  providers = {
    aws        = aws
    cloudflare = cloudflare
    postmark   = postmark
    tls        = tls
  }
}
