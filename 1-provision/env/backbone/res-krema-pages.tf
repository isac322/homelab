# Custom domain for the Krema GitHub Pages site (github_repository_pages.krema).
# Must stay DNS-only: GitHub Pages issues its own certificate for the custom
# domain, which fails behind the Cloudflare proxy.
resource "cloudflare_dns_record" "krema_pages" {
  zone_id = var.cloudflare_main_zone_id
  name    = "krema.bhyoo.com"
  content = "isac322.github.io"
  type    = "CNAME"
  ttl     = 1
  proxied = false
  comment = "Krema GitHub Pages site (isac322/krema)"
}
