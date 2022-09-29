output "external_dns_api_token" {
  value     = cloudflare_api_token.k8s_external_dns.value
  sensitive = true
}
output "cert_manager_api_token" {
  value     = cloudflare_api_token.k8s_cert_manager.value
  sensitive = true
}

data "cloudflare_zone" "domain" {
  zone_id = var.zone_id
}

output "domain" {
  value = data.cloudflare_zone.domain.name
}