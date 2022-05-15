output "cluster_secrets_values" {
  value = yamlencode(
    {
      clusterSecretStore = {
        oracle = {
          vaultOCID     = module.oracle.vault_ocid,
          region        = var.oracle_region,
          tenancyOCID   = var.oracle_tenancy_ocid,
          userOCID      = var.oracle_user_ocid,
          fingerprint   = var.oracle_fingerprint,
          privateKeyB64 = var.oracle_private_key_b64,
        }
      },
      clusterExternalSecret = {
        cloudflareCAAPIKey = {
          externalKeyName = module.oracle.secret_name_cf_ca_api_key
        }
      }
    }
  )
  sensitive = true
}

output "external_dns_api_token" {
  value     = module.cloudflare.external_dns_api_token
  sensitive = true
}
