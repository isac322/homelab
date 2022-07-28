output "external_dns_api_token" {
  value     = cloudflare_api_token.k8s_external_dns.value
  sensitive = true
}
output "cert_manager_api_token" {
  value     = cloudflare_api_token.k8s_cert_manager.value
  sensitive = true
}