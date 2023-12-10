variable "vultr_api_key" {
  type        = string
  description = "https://my.vultr.com/settings/#settingsapi"
  sensitive   = true
}

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