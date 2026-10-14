output "external_secrets_access_key" {
  value     = module.dns_secrets.external_secrets_access_key
  sensitive = true
}
