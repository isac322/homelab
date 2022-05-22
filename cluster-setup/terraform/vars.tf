# You must add IP address of terraform runner to Vultr's allowed IP range.
variable "vultr_api_key" {
  type        = string
  description = "Vultr API Key."
  sensitive   = true
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
variable "backbone_wireguard_ip_subnet" {
  type        = string
  description = "Subnet for VPN only for kubectl"
  default     = "10.222.0.0/24"
}
variable "backbone_worker_count" {
  type        = number
  description = "Number of worker to create client wireguard profile"
}
variable "backbone_wireguard_non_worker_count" {
  type        = number
  description = "Number of non worker clients. (e.g. Laptop of admin to access cluster using kubectl)"
}

# Required permissions for this token: "Zone Read", "DNS Write"
variable "cloudflare_api_token" {
  type        = string
  description = "API token of Cloudflare. This token must have permission `DNS Write` and `Zone Read` at least. Follow https://developers.cloudflare.com/api/tokens/create/"
  sensitive   = true
}
variable "cloudflare_host" {
  type        = string
  description = "Cloudflare Zone (host)"
}