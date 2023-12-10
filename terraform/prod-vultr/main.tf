terraform {
  required_version = ">= 1.6.5, < 2.0.0"

  required_providers {
    vultr = {
      source  = "vultr/vultr"
      version = "2.17.1"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "4.20.0"
    }
  }

  cloud {
    organization = "bhyoo"

    workspaces {
      name = "homelab-vultr"
    }
  }
}

# Configure the Vultr Provider
provider "vultr" {
  api_key = var.vultr_api_key
}

# Configure the Vultr Provider
provider "cloudflare" {
  api_token = var.cloudflare_api_token
}

module "cloudflare" {
  source           = "./cloudflare"
  account_id       = var.cloudflare_account_id
  zone_id          = var.cloudflare_zone_id
  k8s_cluster_name = "vultr"
  k8s_nodes = {
    "v1" = vultr_instance.master1.main_ip
  }
  k8s_controlplane_host = "vultr.k8s"

  providers = {
    cloudflare = cloudflare
  }
}