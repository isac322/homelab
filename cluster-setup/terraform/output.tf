output "wireguard_non_worker_client_configs" {
  value     = module.wireguard.non_worker_clients
  sensitive = true
}
