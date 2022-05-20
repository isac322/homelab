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

variable "cloudflare_email" {
  type        = string
  description = "Cloudflare email address"
}
variable "cloudflare_api_key" {
  type        = string
  description = "Cloudflare API Key"
}
variable "cloudflare_host" {
  type        = string
  description = "Cloudflare Zone (host)"
}