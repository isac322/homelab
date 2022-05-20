# You must add IP address of terraform runner to Vultr's allowed IP range.
variable "vultr_api_key" {
  type        = string
  description = "Vultr API Key."
}
variable "vultr_admin_ssh_keys" {
  type        = map(string)
  description = "list of SSH public key and its name"
}
variable "vultr_backbone_master_instance" {
  type = object({
    region = string
    plan   = string
  })
}

variable "backbone_master_subdomain" {
  type        = string
  description = "Subdomain of backbone cluster's master instance"
}

# Required permissions for this token: "Zone Read", "DNS Write"
variable "cloudflare_api_token" {
  type        = string
  description = "API token of Cloudflare. This token must have permission `DNS Write` and `Zone Read` at least. Follow https://developers.cloudflare.com/api/tokens/create/"
}
variable "cloudflare_host" {
  type        = string
  description = "Cloudflare Zone (host)"
}