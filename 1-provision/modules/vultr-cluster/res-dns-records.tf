locals {
  node_ip_map = {
    for i in keys(var.instance_map) : i => vultr_instance.instances[i].main_ip
  }
}

resource "cloudflare_dns_record" "node" {
  for_each = local.node_ip_map
  zone_id  = var.cloudflare_main_zone_id
  name     = join(".", [each.key, data.cloudflare_zone.main.name])
  content  = each.value
  type     = "A"
  ttl      = 1
  proxied  = false
}
