terraform {
  required_providers {
    oci = {
      source  = "oracle/oci"
      version = ">= 4.74.0, < 5.0.0"
    }
  }
  required_version = ">= 1.1.8, < 2.0.0"
}