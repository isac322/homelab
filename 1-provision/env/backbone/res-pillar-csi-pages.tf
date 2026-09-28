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

# Google Search Console domain-property verification for pillar-csi.bhyoo.com.
# Set to the full "google-site-verification=..." string Search Console shows;
# the record is only created once a value is present.
locals {
  pillar_csi_google_site_verification = null
}

resource "cloudflare_dns_record" "pillar_csi_google_site_verification" {
  count = local.pillar_csi_google_site_verification == null ? 0 : 1

  zone_id = var.cloudflare_main_zone_id
  name    = "pillar-csi.bhyoo.com"
  content = local.pillar_csi_google_site_verification
  type    = "TXT"
  ttl     = 1
  comment = "Google Search Console verification for pillar-csi.bhyoo.com"
}

# Cloudflare Web Analytics for the pillar-csi site. The default provider token
# only issues tokens and edits DNS, so it issues a dedicated token carrying the
# account-level permission the RUM API requires.
data "cloudflare_api_token_permission_groups_list" "account" {
  scope = "com.cloudflare.api.account"
}

resource "cloudflare_api_token" "web_analytics" {
  name = "homelab_web_analytics"

  policies = [
    {
      effect = "allow"
      permission_groups = [
        {
          id = one([
            for p in data.cloudflare_api_token_permission_groups_list.account.result :
            p.id if p.name == "Account Settings Write"
          ])
        },
      ]
      resources = jsonencode({
        "com.cloudflare.api.account.${var.cloudflare_account_id}" = "*"
      })
    },
  ]
}

provider "cloudflare" {
  alias     = "web_analytics"
  api_token = cloudflare_api_token.web_analytics.value
}

# The record is DNS-only, so Cloudflare cannot inject the beacon
# (auto_install); the site embeds the beacon with the site_token output.
resource "cloudflare_web_analytics_site" "pillar_csi" {
  provider = cloudflare.web_analytics

  account_id   = var.cloudflare_account_id
  host         = "pillar-csi.bhyoo.com"
  auto_install = false
}

output "pillar_csi_web_analytics_site_token" {
  description = "Cloudflare Web Analytics beacon token for pillar-csi.bhyoo.com (public; embedded in the site HTML)."
  value       = cloudflare_web_analytics_site.pillar_csi.site_token
}
