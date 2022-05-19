# You must add IP address of terraform runner to Vultr's allowed IP range.
variable "vultr_api_key" {
  type        = string
  description = "Vultr API Key."
}
variable "vultr_admin_ssh_keys" {
  type        = map(string)
  description = "list of SSH public key and its name"
}