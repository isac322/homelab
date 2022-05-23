output "wireguard_non_worker_client_configs" {
  value = {
    for c in module.wireguard.non_worker_clients : c.name => {
      ip                = c.ip
      preshared_key     = c.preshared_key
      private_key       = c.private_key
      public_key        = c.public_key
      server_public_key = module.wireguard.server_public_key
      gateway_ip        = module.wireguard.gateway_ip
      route_cidr        = module.wireguard.route_cidr
    }
  }
  sensitive = true
}
