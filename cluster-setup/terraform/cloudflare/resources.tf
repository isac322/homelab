data "cloudflare_zone" "zone" {
  name = var.zone_name
}

resource "cloudflare_record" "backbone-master" {
  name    = var.backbone_master_record.subdomain
  type    = "A"
  zone_id = data.cloudflare_zone.zone.id
  value   = var.backbone_master_record.ip_address
  proxied = false
}