variable "api_key" {
  type        = string
  description = "Vultr API Key."
}
variable "ssh_keys" {
  type        = map(string)
  description = "list of SSH public key and its name"
}

variable "backbone_master_instance" {
  type = object({
    region   = string
    plan     = string
    hostname = string
  })
}