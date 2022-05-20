# Required permissions for this token: "Zone Read", "DNS Write"
variable "api_token" {
  type        = string
  description = "API token of Cloudflare. This token must have permission `DNS Write` and `Zone Read` at least. Follow https://developers.cloudflare.com/api/tokens/create/"
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