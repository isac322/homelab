variable "oci_api_key_auth" {
  type = tuple([
    object({
      alias           = string
      tenancy_ocid    = string
      user_ocid       = string
      fingerprint     = string
      private_key_b64 = string
    }),
    object({
      alias           = string
      tenancy_ocid    = string
      user_ocid       = string
      fingerprint     = string
      private_key_b64 = string
    }),
    object({
      alias           = string
      tenancy_ocid    = string
      user_ocid       = string
      fingerprint     = string
      private_key_b64 = string
    })
  ])
  sensitive = true
}
variable "oci_region" {
  type = string
}

variable "oci_instance_details" {
  type = map(object({
    host_name           = string
    image_ocid          = string
    ssh_authorized_keys = string
  }))
}

variable "oci_homelab_vcn_cidr" {
  type = map(string)
}

variable "oci_vault_api_key_auth" {
  type = object({
    alias           = string
    tenancy_ocid    = string
    user_ocid       = string
    fingerprint     = string
    private_key_b64 = string
  })
  sensitive = true
}

# Required permissions for this token: "DNS Write", "Zone Read", "API Tokens Write"
variable "cloudflare_api_token" {
  type        = string
  description = "API token of Cloudflare. This token must have permission `DNS Write`, `API Tokens Write` and `Zone Read` at least. Follow https://developers.cloudflare.com/api/tokens/create/"
  sensitive   = true
}
variable "cloudflare_account_id" {
  type        = string
  description = "Cloudflare account id"
  sensitive   = true
}
variable "cloudflare_zone_id" {
  type        = string
  description = "Cloudflare zone id"
  sensitive   = true
}
variable "cloudflare_ca_api_key" {
  type        = string
  description = "Can get on `Origin CA Key` of https://dash.cloudflare.com/profile/api-tokens"
  sensitive   = true
}
