variable "api_key" {
  type        = string
  description = "Vultr API Key."
  sensitive   = true
}
variable "initial_ssh_keys" {
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

variable "wireguard_ip_subnet" {
  type        = string
  description = "Subnet for VPN only for kubectl"
}
variable "wireguard_master_port" {
  type        = number
  description = "Wireguard listening port"
  default     = 51820
}
variable "wireguard_interface_name" {
  type        = string
  description = "Network interface name for wireguard"
  default     = "wg0"
}