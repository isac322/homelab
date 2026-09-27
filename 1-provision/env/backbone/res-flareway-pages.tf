# Custom domain for the Flareway GitHub Pages site (github_repository_pages.flareway).
# Must stay DNS-only: GitHub Pages issues its own certificate for the custom
# domain, which fails behind the Cloudflare proxy.
resource "cloudflare_dns_record" "flareway_pages" {
  zone_id = var.cloudflare_main_zone_id
  name    = "flareway.bhyoo.com"
  content = "isac322.github.io"
  type    = "CNAME"
  ttl     = 1
  proxied = false
  comment = "Flareway GitHub Pages site (isac322/flareway)"
}
