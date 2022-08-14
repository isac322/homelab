output "cluster_secrets_values" {
  value = yamlencode(
    {
      clusterSecretStore = {
        oracle = {
          vaultOCID     = module.oracle_vault.vault_ocid,
          region        = var.oci_region,
          tenancyOCID   = var.oci_vault_api_key_auth.tenancy_ocid,
          userOCID      = var.oci_vault_api_key_auth.user_ocid,
          fingerprint   = var.oci_vault_api_key_auth.fingerprint,
          privateKeyB64 = var.oci_vault_api_key_auth.private_key_b64,
        }
      },
      clusterExternalSecret = {
        cloudflareCAAPIKey = {
          externalKeyName = module.oracle_vault.secret_name_cf_ca_api_key
        }
      }
    }
  )
  sensitive = true
}

output "cluster_node_ips" {
  value = [
    module.oracle_instance_0.node_public_ip,
    module.oracle_instance_1.node_public_ip,
    module.oracle_instance_2.node_public_ip,
  ]
  sensitive = true
}
