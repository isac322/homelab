variable "api_key" {
  type        = string
  description = "Vultr API Key."
}
variable "ssh_keys" {
  type        = map(string)
  description = "list of SSH public key and its name"
}