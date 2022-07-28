terraform {
  required_version = ">= 1.1.8, < 2.0.0"

  cloud {
    organization = "bhyoo"

    workspaces {
      name = "homelab-backbone"
    }
  }
}


module "oracle" {
  source                 = "./oracle"
  fingerprint            = var.oracle_fingerprint
  private_key_b64        = var.oracle_private_key_b64
  region                 = var.oracle_region
  tenancy_ocid           = var.oracle_tenancy_ocid
  user_ocid              = var.oracle_user_ocid
  cloudflare_ca_api_key  = var.cloudflare_ca_api_key
  external_dns_api_token = module.cloudflare.external_dns_api_token
  cert_manager_api_token = module.cloudflare.cert_manager_api_token
}

module "cloudflare" {
  source     = "./cloudflare"
  api_token  = var.cloudflare_api_token
  account_id = var.cloudflare_account_id
}
