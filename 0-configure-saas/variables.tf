variable "cloudflare_email" {
  type      = string
  sensitive = true
}
variable "cloudflare_global_api_key" {
  type      = string
  sensitive = true
}
variable "cloudflare_origin_ca_key" {
  type      = string
  sensitive = true
}

variable "vultr_personal_access_token" {
  type      = string
  sensitive = true
}