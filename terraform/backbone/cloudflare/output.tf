output "external_dns_api_token" {
  value     = cloudflare_api_token.external_dns_api_token.value
  sensitive = true
}