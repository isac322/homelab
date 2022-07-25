output "external_dns_api_token" {
  value     = cloudflare_api_token.external_dns_api_token.value
  sensitive = true
}
output "cert_manager_api_token" {
  value     = cloudflare_api_token.cert_manager_api_token.value
  sensitive = true
}