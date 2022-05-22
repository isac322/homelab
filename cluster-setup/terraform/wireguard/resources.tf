resource "wireguard_asymmetric_key" "server" {
}

resource "wireguard_preshared_key" "global" {
}

resource "wireguard_asymmetric_key" "worker_clients" {
  count = var.worker_count
}

resource "wireguard_asymmetric_key" "non_worker_clients" {
  count = var.non_worker_count
}