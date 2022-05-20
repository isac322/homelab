terraform {
  required_version = ">= 1.1.8, < 2.0.0"

  cloud {
    organization = "bhyoo"

    workspaces {
      name = "cluster-setup"
    }
  }
}


module "vultr" {
  source   = "./vultr"
  api_key  = var.vultr_api_key
  ssh_keys = var.vultr_admin_ssh_keys

  backbone_master_instance = {
    region   = var.vultr_backbone_master_instance.region
    plan     = var.vultr_backbone_master_instance.plan
    hostname = join(".", [var.backbone_master_subdomain, var.cloudflare_host])
  }
}


module "cloudflare" {
  source    = "./cloudflare"
  api_token = var.cloudflare_api_token
  zone_name = var.cloudflare_host

  backbone_master_record = {
    subdomain  = var.backbone_master_subdomain
    ip_address = module.vultr.ip_backbone_master
  }
}