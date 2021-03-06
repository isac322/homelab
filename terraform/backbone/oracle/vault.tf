resource "oci_kms_vault" "vault" {
  compartment_id = var.tenancy_ocid
  display_name   = "backbone_k8s"
  vault_type     = "DEFAULT"
}


resource "oci_vault_secret" "cloudflare_ca_api_key" {
  compartment_id = var.tenancy_ocid

  secret_content {
    content_type = "BASE64"
    content      = base64encode(var.cloudflare_ca_api_key)
  }
  secret_name = "k8s_cloudflare_ca_api_key"
  vault_id    = oci_kms_vault.vault.id
  key_id      = oci_kms_key.vault_key.id
}

resource "oci_vault_secret" "external_dns_api_token" {
  compartment_id = var.tenancy_ocid

  secret_content {
    content_type = "BASE64"
    content      = base64encode(var.external_dns_api_token)
  }
  secret_name = "k8s_external_dns_api_token"
  vault_id    = oci_kms_vault.vault.id
  key_id      = oci_kms_key.vault_key.id
}

resource "oci_vault_secret" "cert_manager_api_token" {
  compartment_id = var.tenancy_ocid

  secret_content {
    content_type = "BASE64"
    content      = base64encode(var.cert_manager_api_token)
  }
  secret_name = "k8s_cert_manager_api_token"
  vault_id    = oci_kms_vault.vault.id
  key_id      = oci_kms_key.vault_key.id
}

resource "oci_kms_key" "vault_key" {
  compartment_id = var.tenancy_ocid
  display_name   = "backbone_k8s"

  key_shape {
    algorithm = "AES"
    length    = 32
  }
  management_endpoint = oci_kms_vault.vault.management_endpoint

  protection_mode = "HSM"
}
