data "cloudflare_zone" "main" {
  zone_id = var.cloudflare_main_zone_id
}

resource "vultr_instance" "instances" {
  for_each = var.instance_map

  plan              = each.value.plan
  region            = each.value.region
  os_id             = 2284
  label             = join(".", [each.key, data.cloudflare_zone.main.name])
  hostname          = join(".", [each.key, data.cloudflare_zone.main.name])
  enable_ipv6       = true
  backups           = "disabled"
  ddos_protection   = false
  activation_email  = false
  vpc_ids           = [vultr_vpc.homelab.id]
  ssh_key_ids       = [for k in vultr_ssh_key.bhyoo : k.id]
  script_id         = vultr_startup_script.cleanup_ubuntu_24_04.id
  firewall_group_id = vultr_firewall_group.homelab.id
}

resource "vultr_ssh_key" "bhyoo" {
  for_each = var.ssh_keys

  name    = each.key
  ssh_key = each.value
}

resource "vultr_startup_script" "cleanup_ubuntu_24_04" {
  name   = "cleanup_ubuntu_24_04"
  type   = "boot"
  script = filebase64("${path.module}/cleanup_ubuntu_24_04.sh")
}
