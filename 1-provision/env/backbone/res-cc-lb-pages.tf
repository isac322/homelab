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

# Public DNS ownership challenge issued by GitHub for the isac322 account.
# The account-level verification is web-only; the DNS record remains IaC-owned.
resource "cloudflare_dns_record" "cc_lb_github_pages_verification" {
  zone_id = var.cloudflare_main_zone_id
  name    = "_github-pages-challenge-isac322.cc-lb.bhyoo.com"
  content = "b5a671a9955e28c5d7df16e0c8620d"
  type    = "TXT"
  ttl     = 1
  comment = "GitHub Pages ownership verification for cc-lb.bhyoo.com (isac322)"
}

# Public DNS ownership challenge issued by Search Console for the Domain property.
resource "cloudflare_dns_record" "cc_lb_google_site_verification" {
  zone_id = var.cloudflare_main_zone_id
  name    = local.cc_lb_pages_cname
  content = "google-site-verification=IsgjwVQ48J1Dc6JEydyMc5umgjDC3bYXPTojSH_TYbQ"
  type    = "TXT"
  ttl     = 1
  comment = "Google Search Console ownership verification for cc-lb.bhyoo.com"
}

# Bing issues a relative alias label for the registered cc-lb site.
# Keep the public ownership proof under that hostname, not the zone apex.
resource "cloudflare_dns_record" "cc_lb_bing_verification" {
  zone_id = var.cloudflare_main_zone_id
  name    = "92fd7881cdd0b3de3ba7cb4466447323.${local.cc_lb_pages_cname}"
  content = "verify.bing.com"
  type    = "CNAME"
  ttl     = 1
  proxied = false
  comment = "Bing Webmaster Tools ownership verification for cc-lb.bhyoo.com"
}
