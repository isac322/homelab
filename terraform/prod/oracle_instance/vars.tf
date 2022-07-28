variable "compartment_ocid" {
  type      = string
  sensitive = true
}
variable "tenancy_ocid" {
  type      = string
  sensitive = true
}

variable "instance_detail" {
  type = object({
    host_name           = string
    image_ocid          = string
    ssh_authorized_keys = string
  })
}

variable "homelab_cidr_block" {
  type = string
}
variable "lpg_peer_requesters" {
  type = list(object({
    destination_cidr = string
    alias            = string
  }))
  sensitive = true
}
variable "lpg_peer_to_accepts" {
  type = list(object({
    destination_cidr = string
    gateway_ocid     = string
    alias            = string
  }))
  sensitive = true
}

variable "lpg_acceptor_tenancy_ocids" {
  type = map(object({
    tenancy_ocid = string
    group_ocid   = string
  }))
  sensitive = true
}
variable "lpg_requester_tenancy_ocids" {
  type      = map(string)
  sensitive = true
}

variable "cloudflare_ca_api_key" {
  type = string
}
#variable "external_dns_api_token" {
#  type = string
#}
#variable "cert_manager_api_token" {
#  type = string
#}