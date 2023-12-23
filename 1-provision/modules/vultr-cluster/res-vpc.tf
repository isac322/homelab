resource "vultr_vpc2" "homelab" {
  description   = "homelab"
  region        = var.vpc_network.region
  ip_block      = var.vpc_network.network
  prefix_length = var.vpc_network.prefix
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

resource "vultr_firewall_rule" "homelab-wireguard-v4" {
  firewall_group_id = vultr_firewall_group.homelab.id
  ip_type           = "v4"
  protocol          = "udp"
  port              = "51902"
  subnet            = "0.0.0.0"
  subnet_size       = 0
}

resource "vultr_firewall_rule" "homelab-wireguard-v6" {
  firewall_group_id = vultr_firewall_group.homelab.id
  ip_type           = "v6"
  protocol          = "udp"
  port              = "51902"
  subnet            = "::"
  subnet_size       = 0
}

resource "vultr_firewall_rule" "homelab-https-v4" {
  firewall_group_id = vultr_firewall_group.homelab.id
  ip_type           = "v4"
  protocol          = "tcp"
  port              = "443"
  subnet            = "0.0.0.0"
  subnet_size       = 0
}

resource "vultr_firewall_rule" "homelab-https-v6" {
  firewall_group_id = vultr_firewall_group.homelab.id
  ip_type           = "v6"
  protocol          = "tcp"
  port              = "443"
  subnet            = "::"
  subnet_size       = 0
}
