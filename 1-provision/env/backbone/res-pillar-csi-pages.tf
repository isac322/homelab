# Custom domain for the pillar-csi GitHub Pages site (github_repository_pages.pillar_csi).
# Must stay DNS-only: GitHub Pages issues its own certificate for the custom
# domain, which fails behind the Cloudflare proxy.
resource "cloudflare_dns_record" "pillar_csi_pages" {
  zone_id = var.cloudflare_main_zone_id
  name    = "pillar-csi.bhyoo.com"
  content = "isac322.github.io"
  type    = "CNAME"
  ttl     = 1
  proxied = false
  comment = "pillar-csi GitHub Pages site (isac322/pillar-csi)"
}
