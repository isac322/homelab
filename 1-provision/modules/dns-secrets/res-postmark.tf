resource "postmark_domain" "bhyoo" {
  name               = "bhyoo.com"
  return_path_domain = "pm-bounces.bhyoo.com"
}

resource "cloudflare_dns_record" "postmark_dkim" {
  zone_id = var.cloudflare_main_zone_id
  name    = coalesce(postmark_domain.bhyoo.dkim_pending_host, postmark_domain.bhyoo.dkim_host)
  content = coalesce(postmark_domain.bhyoo.dkim_pending_text_value, postmark_domain.bhyoo.dkim_text_value)
  type    = "TXT"
  ttl     = 1
}

resource "cloudflare_dns_record" "postmark_return_path" {
  zone_id = var.cloudflare_main_zone_id
  name    = postmark_domain.bhyoo.return_path_domain
  content = postmark_domain.bhyoo.return_path_domain_cname_value
  type    = "CNAME"
  ttl     = 1
  proxied = false
}

resource "postmark_server" "vaultwarden" {
  name               = "homelab-vaultwarden"
  color              = "blue"
  delivery_type      = "Live"
  smtp_api_activated = true
  track_links        = "None"
  track_opens        = false
}

resource "postmark_server" "immich" {
  name               = "homelab-immich"
  color              = "green"
  delivery_type      = "Live"
  smtp_api_activated = true
  track_links        = "None"
  track_opens        = false
}
