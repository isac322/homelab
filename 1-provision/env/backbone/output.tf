output "external_secrets_access_key" {
  value     = module.dns_secrets.external_secrets_access_key
  sensitive = true
}

output "democratic_csi_ssh_public_key" {
  value = module.dns_secrets.democratic_csi_ssh_public_key
}
