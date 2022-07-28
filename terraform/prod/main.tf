terraform {
  required_version = ">= 1.1.8, < 2.0.0"

  required_providers {
    oci = {
      source  = "oracle/oci"
      version = ">= 4.74.0, < 5.0.0"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = ">= 3.14.0, < 4.0.0"
    }
  }

  cloud {
    organization = "bhyoo"

    workspaces {
      name = "homelab-prod"
    }
  }
}

provider "oci" {
  alias = "vault"

  fingerprint  = var.oci_vault_api_key_auth.fingerprint
  private_key  = base64decode(var.oci_vault_api_key_auth.private_key_b64)
  region       = var.oci_region
  tenancy_ocid = var.oci_vault_api_key_auth.tenancy_ocid
  user_ocid    = var.oci_vault_api_key_auth.user_ocid
}

module "oracle_vault" {
  source                 = "./oracle_vault"
  cert_manager_api_token = module.cloudflare.cert_manager_api_token
  cloudflare_ca_api_key  = var.cloudflare_ca_api_key
  external_dns_api_token = module.cloudflare.external_dns_api_token

  compartment_id = var.oci_vault_api_key_auth.tenancy_ocid

  providers = {
    oci = oci.vault
  }
}


provider "cloudflare" {
  api_token = var.cloudflare_api_token
}

module "cloudflare" {
  source    = "./cloudflare"
  zone_name = var.cloudflare_host
}


#########################################################################################################
# FIXME: terraform does not support dynamic provider. https://github.com/hashicorp/terraform/issues/25244
#########################################################################################################

provider "oci" {
  alias = "oci1"

  fingerprint  = var.oci_api_key_auth[0].fingerprint
  private_key  = base64decode(var.oci_api_key_auth[0].private_key_b64)
  region       = var.oci_region
  tenancy_ocid = var.oci_api_key_auth[0].tenancy_ocid
  user_ocid    = var.oci_api_key_auth[0].user_ocid
}

provider "oci" {
  alias = "oci2"

  fingerprint  = var.oci_api_key_auth[1].fingerprint
  private_key  = base64decode(var.oci_api_key_auth[1].private_key_b64)
  region       = var.oci_region
  tenancy_ocid = var.oci_api_key_auth[1].tenancy_ocid
  user_ocid    = var.oci_api_key_auth[1].user_ocid
}

provider "oci" {
  alias = "oci3"

  fingerprint  = var.oci_api_key_auth[2].fingerprint
  private_key  = base64decode(var.oci_api_key_auth[2].private_key_b64)
  region       = var.oci_region
  tenancy_ocid = var.oci_api_key_auth[2].tenancy_ocid
  user_ocid    = var.oci_api_key_auth[2].user_ocid
}


module "oracle_instance_0" {
  source = "./oracle_instance"

  tenancy_ocid     = var.oci_api_key_auth[0].tenancy_ocid
  compartment_ocid = var.oci_api_key_auth[0].tenancy_ocid

  instance_detail = var.oci_instance_details[var.oci_api_key_auth[0].alias]

  homelab_cidr_block = var.oci_homelab_vcn_cidr[var.oci_api_key_auth[0].alias]
  lpg_peer_requesters = [
    {
      destination_cidr = var.oci_homelab_vcn_cidr[var.oci_api_key_auth[1].alias]
      alias            = var.oci_api_key_auth[1].alias
    },
  ]
  lpg_peer_to_accepts = [
    {
      destination_cidr = var.oci_homelab_vcn_cidr[var.oci_api_key_auth[2].alias]
      gateway_ocid     = module.oracle_instance_2.peer_requesting_lpg_gateway_ocid[var.oci_api_key_auth[0].alias]
      alias            = var.oci_api_key_auth[2].alias
    },
  ]

  lpg_acceptor_tenancy_ocids = {
    (var.oci_api_key_auth[2].alias) = {
      tenancy_ocid = var.oci_api_key_auth[2].tenancy_ocid
      group_ocid   = module.oracle_instance_2.group_ocid
    },
  }
  lpg_requester_tenancy_ocids = {
    (var.oci_api_key_auth[1].alias) = var.oci_api_key_auth[1].tenancy_ocid,
  }

  cloudflare_ca_api_key = var.cloudflare_ca_api_key
  #  external_dns_api_token = module.cloudflare.external_dns_api_token
  #  cert_manager_api_token = module.cloudflare.cert_manager_api_token

  providers = {
    oci = oci.oci1
  }
}

module "oracle_instance_1" {
  source = "./oracle_instance"

  tenancy_ocid     = var.oci_api_key_auth[1].tenancy_ocid
  compartment_ocid = var.oci_api_key_auth[1].tenancy_ocid

  instance_detail = var.oci_instance_details[var.oci_api_key_auth[1].alias]

  homelab_cidr_block = var.oci_homelab_vcn_cidr[var.oci_api_key_auth[1].alias]
  lpg_peer_requesters = [
    {
      destination_cidr = var.oci_homelab_vcn_cidr[var.oci_api_key_auth[2].alias]
      alias            = var.oci_api_key_auth[2].alias
    },
  ]
  lpg_peer_to_accepts = [
    {
      destination_cidr = var.oci_homelab_vcn_cidr[var.oci_api_key_auth[0].alias]
      gateway_ocid     = module.oracle_instance_0.peer_requesting_lpg_gateway_ocid[var.oci_api_key_auth[1].alias]
      alias            = var.oci_api_key_auth[0].alias
    },
  ]

  lpg_acceptor_tenancy_ocids = {
    (var.oci_api_key_auth[0].alias) = {
      tenancy_ocid = var.oci_api_key_auth[0].tenancy_ocid
      group_ocid   = module.oracle_instance_0.group_ocid
    },
  }
  lpg_requester_tenancy_ocids = {
    (var.oci_api_key_auth[2].alias) = var.oci_api_key_auth[2].tenancy_ocid,
  }

  cloudflare_ca_api_key = var.cloudflare_ca_api_key
  #  external_dns_api_token = module.cloudflare.external_dns_api_token
  #  cert_manager_api_token = module.cloudflare.cert_manager_api_token

  providers = {
    oci = oci.oci2
  }
}

module "oracle_instance_2" {
  source = "./oracle_instance"

  tenancy_ocid     = var.oci_api_key_auth[2].tenancy_ocid
  compartment_ocid = var.oci_api_key_auth[2].tenancy_ocid

  instance_detail = var.oci_instance_details[var.oci_api_key_auth[2].alias]

  homelab_cidr_block = var.oci_homelab_vcn_cidr[var.oci_api_key_auth[2].alias]
  lpg_peer_requesters = [
    {
      destination_cidr = var.oci_homelab_vcn_cidr[var.oci_api_key_auth[0].alias]
      alias            = var.oci_api_key_auth[0].alias
    },
  ]
  lpg_peer_to_accepts = [
    {
      destination_cidr = var.oci_homelab_vcn_cidr[var.oci_api_key_auth[1].alias]
      gateway_ocid     = module.oracle_instance_1.peer_requesting_lpg_gateway_ocid[var.oci_api_key_auth[2].alias]
      alias            = var.oci_api_key_auth[1].alias
    },
  ]

  lpg_acceptor_tenancy_ocids = {
    (var.oci_api_key_auth[1].alias) = {
      tenancy_ocid = var.oci_api_key_auth[1].tenancy_ocid
      group_ocid   = module.oracle_instance_1.group_ocid
    },
  }
  lpg_requester_tenancy_ocids = {
    (var.oci_api_key_auth[0].alias) = var.oci_api_key_auth[0].tenancy_ocid,
  }

  cloudflare_ca_api_key = var.cloudflare_ca_api_key
  #  external_dns_api_token = module.cloudflare.external_dns_api_token
  #  cert_manager_api_token = module.cloudflare.cert_manager_api_token

  providers = {
    oci = oci.oci3
  }
}

#module "cloudflare" {
#  source    = "./cloudflare"
#  api_token = var.cloudflare_api_token
#  zone_name = var.cloudflare_host
#}
