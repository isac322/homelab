terraform {
  required_version = ">= 1.6.5, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.30"
    }
    tfe = {
      source  = "hashicorp/tfe"
      version = "~> 0.50"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 4.20"
    }
  }
}

provider "aws" {
  region = "ap-northeast-2"

  default_tags {
    tags = {
      Owner               = "bhyoo"
      Project             = "homelab"
      terraform-base-path = join("/", [replace(path.cwd, "/^.*?(homelab\\/)/", "$1"), "boostrap-saas"])
    }
  }
}

provider "cloudflare" {
  api_key = var.cloudflare_global_api_key
  email   = var.cloudflare_email
}

module "saas" {
  source = "./boostrap-saas"

  cloudflare_email            = var.cloudflare_email
  cloudflare_global_api_key   = var.cloudflare_global_api_key
  cloudflare_origin_ca_key    = var.cloudflare_origin_ca_key
  vultr_personal_access_token = var.vultr_personal_access_token

  aws_admin_account_id  = 825808295984
  aws_admin_family_name = "Yoo"
  aws_admin_given_name  = "Byeonghoon"
  aws_admin_user_name   = "bhyoo"
  aws_admin_email       = "bhyoo@bhyoo.com"

  cloudflare_main_domain = "bhyoo.com"

  tfe_organization = "bhyoo"
  tfe_email        = "bhyoo@bhyoo.com"

  providers = {
    aws        = aws
    tfe        = tfe
    cloudflare = cloudflare
  }
}