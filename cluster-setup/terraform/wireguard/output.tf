output "server_public_key" {
  value = wireguard_asymmetric_key.server.public_key
}
output "interface_name" {
  value = var.interface_name
}
output "route_cidr" {
  value = var.ip_subnet_cidr
}
output "gateway_ip" {
  value = local.server_ip
}

locals {
  server_ip = cidrhost(var.ip_subnet_cidr, 1)

  worker_clients = [
  for i, c in wireguard_asymmetric_key.worker_clients : {
    private_key   = c.private_key
    public_key    = c.public_key
    preshared_key = wireguard_preshared_key.global.key
    ip            = cidrhost(var.ip_subnet_cidr, i + 2)  # IP must start from 1 and avoid master's IP
  }
  ]

  non_worker_clients = [
  for k, c in wireguard_asymmetric_key.non_worker_client : {
    private_key   = c.private_key
    public_key    = c.public_key
    preshared_key = wireguard_preshared_key.global.key
    ip            = cidrhost(var.ip_subnet_cidr, index(var.non_workers, k) + 100)
    name          = k
  }
  ]
}

output "server_systemd_networkd_netdev" {
  value = templatefile(
    "${path.module}/server_netdev.tftpl",
    {
      interface_name = var.interface_name
      subnet         = var.ip_subnet_cidr
      private_key    = wireguard_asymmetric_key.server.private_key
      port           = var.server_port
      clients        = concat(local.worker_clients, local.non_worker_clients)
    }
  )
  sensitive = true
}

output "server_systemd_networkd_network" {
  value = templatefile(
    "${path.module}/server_network.tftpl",
    {
      interface_name = var.interface_name
      subnet         = var.ip_subnet_cidr
      ip             = local.server_ip
    }
  )
  sensitive = true
}

output "workers_systemd_networkd_network" {
  value = [
  for c in local.worker_clients : templatefile(
    "${path.module}/client_network.tftpl",
    {
      interface_name = var.interface_name
      subnet         = var.ip_subnet_cidr
      ip             = c.ip
      server_ip      = local.server_ip
    }
  )
  ]
  sensitive = true
}

output "workers_systemd_networkd_netdev" {
  value = [
  for c in local.worker_clients : templatefile(
    "${path.module}/client_netdev.tftpl",
    {
      interface_name    = var.interface_name
      subnet            = var.ip_subnet_cidr
      ip                = c.ip
      private_key       = c.private_key
      server_public_key = wireguard_asymmetric_key.server.public_key
      server_host       = var.server_host
      server_port       = var.server_port
      server_ip         = local.server_ip
      preshared_key     = wireguard_preshared_key.global.key
    }
  )
  ]
  sensitive = true
}

output "non_worker_clients" {
  value     = local.non_worker_clients
  sensitive = true
}