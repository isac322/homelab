data "cloudflare_zone" "main" {
  zone_id = var.cloudflare_main_zone_id
}

resource "vultr_instance" "instances" {
  for_each = var.instance_map

  plan              = each.value.plan
  region            = each.value.region
  os_id             = 2760
  label             = join(".", [each.key, data.cloudflare_zone.main.name])
  hostname          = join(".", [each.key, data.cloudflare_zone.main.name])
  enable_ipv6       = false
  backups           = "disabled"
  ddos_protection   = false
  activation_email  = false
  ssh_key_ids       = [for k in vultr_ssh_key.bhyoo : k.id]
  firewall_group_id = vultr_firewall_group.homelab.id
}

resource "vultr_ssh_key" "bhyoo" {
  for_each = var.ssh_keys

  name    = each.key
  ssh_key = each.value
}
