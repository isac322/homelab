output "vault_ocid" {
  value      = oci_kms_vault.vault.id
  depends_on = [oci_kms_vault.vault]
  sensitive  = true
}

output "secret_name_cf_ca_api_key" {
  value = oci_vault_secret.cloudflare_ca_api_key.secret_name
}

output "secret_name_external_dns_api_token" {
  value = oci_vault_secret.external_dns_api_token.secret_name
}