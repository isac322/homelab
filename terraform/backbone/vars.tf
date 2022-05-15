variable "oracle_tenancy_ocid" {
  type = string
}
variable "oracle_user_ocid" {
  type = string
}
variable "oracle_fingerprint" {
  type = string
}
variable "oracle_private_key_b64" {
  type = string
}
variable "oracle_region" {
  type = string
}

# Required permissions for this token: "Zone Read", "API Tokens Write"
variable "cloudflare_api_token" {
  type = string
}
variable "cloudflare_host" {
  type = string
}
variable "cloudflare_ca_api_key" {
  type = string
}
