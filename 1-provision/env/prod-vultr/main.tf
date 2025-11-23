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
      version = "~> 2.27.1"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.1.0"
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
  # shared_config_files      = ["/home/bhyoo/.aws/config"]
  # shared_credentials_files = ["/home/bhyoo/.aws/credentials"]
  # profile                  = "personal"

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
      plan   = "vc2-1c-2gb"
      region = "icn"
    }
  }
  vpc_network = {
    network = "10.34.112.0"
    region  = "icn"
    prefix  = 20
  }
  ssh_keys = {
    desktop = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIJn1FChNUhCeKJyYZwWAt9v5q1Xm+fVwHDufTPRGsrKt bhyoo@bhyoo-desktop"
    mobile  = "ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBB+cibIZ3Lb2CqszA7NTNoro5riObOfz3cqHeeocM5DX2zKePCCNNUJz6CnkPjBIh23pYfSH+HCyOldoi/2ynLw="
    tablet  = "ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBEZj/byuEy23ADQpubcvI6e6wuiOoGnHbYLoNx9icWo5c8KS2gf3RMRQ4hptvr/UVT9FIA5rD06yeKXYLBRNW4s="
    laptop  = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPo4HReAviwkmOkdPJcwzjF0kINMdBoy2p+P7qxrOM3O bhyoo@latitude7490-manjaro"
    office  = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPjoa/Ig+76qbbUSAavPGzLoBI36jLPdyMKg8XLli0Ib bhyoo@isac-macbook.local"
  }

  cloudflare_main_zone_id = var.cloudflare_main_zone_id
  k8s_controlplane_host   = "vultr.k8s"

  providers = {
    cloudflare = cloudflare
    vultr      = vultr
  }
}
