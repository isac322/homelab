locals {
  node_ip_map = {
    for i in keys(var.instance_map) : i => vultr_instance.instances[i].main_ip
  }
}

resource "cloudflare_record" "node" {
  for_each = local.node_ip_map
  zone_id  = var.cloudflare_main_zone_id
  name     = each.key
  value    = each.value
  type     = "A"
  proxied  = false
}

resource "cloudflare_record" "k8s_control_plane" {
  for_each = local.node_ip_map
  zone_id  = var.cloudflare_main_zone_id
  name     = var.k8s_controlplane_host
  value    = each.value
  type     = "A"
  proxied  = false
}
