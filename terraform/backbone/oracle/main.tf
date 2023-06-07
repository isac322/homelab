terraform {
  required_providers {
    oci = {
      source  = "oracle/oci"
      version = ">= 4.74.0, < 6.0.0"
    }
  }
  required_version = ">= 1.1.8, < 2.0.0"
}

provider "oci" {
  tenancy_ocid     = var.tenancy_ocid
  user_ocid        = var.user_ocid
  fingerprint      = var.fingerprint
  private_key      = base64decode(var.private_key_b64)
  region           = var.region
}