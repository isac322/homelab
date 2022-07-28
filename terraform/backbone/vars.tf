variable "oracle_tenancy_ocid" {
  type        = string
  description = "OCID that can find at https://cloud.oracle.com/tenancy"
  sensitive   = true
}
variable "oracle_user_ocid" {
  type        = string
  description = "OCID that can find at https://cloud.oracle.com/identity/users"
  sensitive   = true
}
variable "oracle_fingerprint" {
  type        = string
  description = "Fingerprint of Signing key for OCI API key. Follow https://docs.oracle.com/en-us/iaas/Content/API/Concepts/apisigningkey.htm"
}
variable "oracle_private_key_b64" {
  type        = string
  description = "Signing key for OCI API key that encoded with base64. Follow https://docs.oracle.com/en-us/iaas/Content/API/Concepts/apisigningkey.htm"
  sensitive   = true
}
variable "oracle_region" {
  type        = string
  description = "region of OCI"
}

# Required permissions for this token: "Zone Read", "API Tokens Write"
variable "cloudflare_api_token" {
  type        = string
  description = "API token of Cloudflare. This token must have permission `API Tokens Write` and `Zone Read` at least. Follow https://developers.cloudflare.com/api/tokens/create/"
  sensitive   = true
}
variable "cloudflare_account_id" {
  type        = string
  description = "Cloudflare account id"
  sensitive   = true
}
variable "cloudflare_ca_api_key" {
  type        = string
  description = "Can get on `Origin CA Key` of https://dash.cloudflare.com/profile/api-tokens"
  sensitive   = true
}
