resource "vultr_firewall_group" "homelab" {
  description = "homelab"
}

resource "vultr_firewall_rule" "homelab-ssh-v4" {
  firewall_group_id = vultr_firewall_group.homelab.id
  ip_type           = "v4"
  protocol          = "tcp"
  port              = "22"
  subnet            = "0.0.0.0"
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
