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
  source           = "./vultr"
  api_key          = var.vultr_api_key
  initial_ssh_keys = var.vultr_admin_ssh_keys

  backbone_master_instance = {
    region   = var.vultr_backbone_master_instance.region
    plan     = var.vultr_backbone_master_instance.plan
    hostname = join(".", [var.backbone_master_subdomain, var.cloudflare_host])
  }

  wireguard_interface_name                  = module.wireguard.interface_name
  wireguard_server_systemd_networkd_netdev  = module.wireguard.server_systemd_networkd_netdev
  wireguard_server_systemd_networkd_network = module.wireguard.server_systemd_networkd_network
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

module "wireguard" {
  source           = "./wireguard"
  worker_count     = var.backbone_worker_count
  non_worker_count = length(var.vultr_admin_ssh_keys)
  ip_subnet_cidr   = cidrsubnet(var.backbone_wireguard_ip_subnet, 0, 0)
  server_host      = "${var.backbone_master_subdomain}.${var.cloudflare_host}"
}