# Custom domain for the cc-lb GitHub Pages site (github_repository_pages.cc_lb).
# Must stay DNS-only: GitHub Pages issues its own certificate for the custom
# domain, which fails behind the Cloudflare proxy.
resource "cloudflare_dns_record" "cc_lb_pages" {
  zone_id = var.cloudflare_main_zone_id
  name    = local.cc_lb_pages_cname
  content = "isac322.github.io"
  type    = "CNAME"
  ttl     = 1
  proxied = false
  comment = "cc-lb GitHub Pages site (isac322/cc-lb)"
}
