# You must add IP address of terraform runner to Vultr's allowed IP range.
variable "vultr_api_key" {
  type        = string
  description = "Vultr API Key."
}