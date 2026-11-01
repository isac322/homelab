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
    vultr = {
      source  = "vultr/vultr"
      version = "~> 2.33.2"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.4.2"
    }
  }

  cloud {
    organization = "bhyoo"

    workspaces {
      name = "homelab-vultr"
    }
  }
}

provider "vultr" {
  api_key = var.vultr_pat
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
      terraform-base-path = "homelab/1-provision/env/prod-vultr"
    }
  }
}

module "dns_secrets" {
  source = "./dns-secrets"

  k8s_cluster_name                            = "vultr"
  cloudflare_account_id                       = var.cloudflare_account_id
  aws_iam_group_name_cf_origin_ca_cert_issuer = var.aws_iam_group_name_cf_origin_ca_cert_issuer

  providers = {
    aws        = aws
    cloudflare = cloudflare
    tls        = tls
  }
}

module "cluster" {
  source = "./vultr-cluster"

  instance_map = {
    v1 = {
      plan   = "vc2-1c-1gb"
      region = "sea"
    }
  }
  ssh_keys = {
    for name in ["desktop", "laptop", "mobile", "tablet", "office"] :
    name => trimspace(file("${path.module}/ssh_pub_keys/${name}.pub"))
  }

  cloudflare_main_zone_id = var.cloudflare_main_zone_id

  providers = {
    cloudflare = cloudflare
    vultr      = vultr
  }
}
