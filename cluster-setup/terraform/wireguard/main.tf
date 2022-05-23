terraform {
  required_providers {
    wireguard = {
      source = "OJFord/wireguard"
      version = "0.2.1+1"
    }
  }
  required_version = ">= 1.1.8, < 2.0.0"
}
