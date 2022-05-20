variable "api_key" {
  type        = string
  description = "Cloudflare API Key"
}
variable "email" {
  type        = string
  description = "Cloudflare email address"
}
variable "zone_name" {
  type        = string
  description = "Cloudflare Zone (host)"
}

variable "backbone_master_record" {
  type = object({
    subdomain  = string
    ip_address = string
  })
  description = "DNS record info of backbone cluster's master"
}