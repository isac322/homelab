# Cookie-free Cloudflare Web Analytics for the cc-lb project site. Reuses the
# shared web_analytics token/provider from res-pillar-csi-pages.tf.
#
# The Pages record is DNS-only, so Cloudflare cannot inject the beacon
# (auto_install); the site build embeds it with site_token instead.
resource "cloudflare_web_analytics_site" "cc_lb" {
  provider = cloudflare.web_analytics

  account_id   = var.cloudflare_account_id
  host         = local.cc_lb_pages_cname
  auto_install = false
}

# site_token is the public beacon token rendered into every page's HTML, not
# an API credential, so it is stored as an Actions variable rather than a
# secret. Only the master Pages build reads it.
resource "github_actions_variable" "cc_lb_public_analytics_token" {
  repository    = github_repository.cc_lb.name
  variable_name = "PUBLIC_ANALYTICS_TOKEN"
  value         = cloudflare_web_analytics_site.cc_lb.site_token
}

output "cc_lb_web_analytics_site_token" {
  description = "Cloudflare Web Analytics beacon token for cc-lb.bhyoo.com (public; embedded in the site HTML)."
  value       = cloudflare_web_analytics_site.cc_lb.site_token
}

output "cc_lb_web_analytics_site_tag" {
  description = "Cloudflare Web Analytics site tag for cc-lb.bhyoo.com (identifies the site in the account dashboard)."
  value       = cloudflare_web_analytics_site.cc_lb.site_tag
}
