resource "vultr_vpc2" "homelab" {
  description   = "homelab"
  region        = "icn"
  ip_block      = "10.34.112.0"
  prefix_length = 20
}

resource "vultr_firewall_group" "homelab" {
  description = "homelab"
}

resource "vultr_firewall_rule" "homelab-dns-v4" {
  for_each = {
    "v4-udp"        = { ip_type = "v4", protocol = "udp", port = 53 }
    "v4-tcp"        = { ip_type = "v4", protocol = "tcp", port = 53 }
    "v4-secure-tcp" = { ip_type = "v4", protocol = "tcp", port = 853 }
  }

  firewall_group_id = vultr_firewall_group.homelab.id
  ip_type           = "v4"
  protocol          = each.value["protocol"]
  port              = each.value["port"]
  subnet            = "0.0.0.0"
  subnet_size       = 0
}

resource "vultr_firewall_rule" "homelab-dns" {
  for_each = {
    "v6-udp"        = { ip_type = "v6", protocol = "udp", port = 53 }
    "v6-tcp"        = { ip_type = "v6", protocol = "tcp", port = 53 }
    "v6-secure-tcp" = { ip_type = "v6", protocol = "tcp", port = 853 }
  }

  firewall_group_id = vultr_firewall_group.homelab.id
  ip_type           = "v6"
  protocol          = each.value["protocol"]
  port              = each.value["port"]
  subnet            = "::"
  subnet_size       = 0
}

resource "vultr_firewall_rule" "homelab-ssh-v4" {
  firewall_group_id = vultr_firewall_group.homelab.id
  ip_type           = "v4"
  protocol          = "tcp"
  port              = "22"
  subnet            = "0.0.0.0"
  subnet_size       = 0
}

resource "vultr_firewall_rule" "homelab-ssh-v6" {
  firewall_group_id = vultr_firewall_group.homelab.id
  ip_type           = "v6"
  protocol          = "tcp"
  port              = "22"
  subnet            = "::"
  subnet_size       = 0
}

resource "vultr_instance" "master1" {
  plan             = "vc2-1c-1gb"
  region           = "icn"
  os_id            = 1743
  label            = "v1.bhyoo.com"
  hostname         = "v1.bhyoo.com"
  enable_ipv6      = true
  backups          = "disabled"
  ddos_protection  = false
  activation_email = false
  vpc2_ids = [
    vultr_vpc2.homelab.id
  ]
  ssh_key_ids       = [for k in vultr_ssh_key.bhyoo : k.id]
  script_id         = vultr_startup_script.cleanup_ubuntu_22_04.id
  firewall_group_id = vultr_firewall_group.homelab.id
}

resource "vultr_ssh_key" "bhyoo" {
  for_each = {
    desktop = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIJn1FChNUhCeKJyYZwWAt9v5q1Xm+fVwHDufTPRGsrKt bhyoo@bhyoo-desktop"
    mobile  = "ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBMSLM7M7rcPnxRXOVUn3aNtCxCaxQmhIBiHvYIphQzOXnxVSVjKDzw8Ieb3jl3HcUTJ6RMfGdceukSx6Czo99B4="
    tablet  = "ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBApW7dBpU2RFbv+7IQF2wg1qyebp7NVLY6bOw+pqra1jqfOxxXGDqnzg8eEFG5IZdhr+PCsYn0go3nXOSm37aZc="
    laptop  = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPo4HReAviwkmOkdPJcwzjF0kINMdBoy2p+P7qxrOM3O bhyoo@latitude7490-manjaro"
  }

  name    = each.key
  ssh_key = each.value
}

resource "vultr_startup_script" "cleanup_ubuntu_22_04" {
  name   = "cleanup_ubuntu_22_04"
  type   = "boot"
  script = filebase64("${path.module}/cleanup_ubuntu_22_04.sh")
}