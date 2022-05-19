terraform {
  required_version = ">= 1.1.8, < 2.0.0"

  cloud {
    organization = "bhyoo"

    workspaces {
      name = "cluster-setup"
    }
  }
}


module "vultr" {
  source  = "./vultr"
  api_key = var.vultr_api_key
}
