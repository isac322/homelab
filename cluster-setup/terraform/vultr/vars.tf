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


variable "wireguard_interface_name" {
  type        = string
  description = "Network interface name for wireguard"
}
variable "wireguard_server_systemd_networkd_netdev" {
  type      = string
  sensitive = true
}
variable "wireguard_server_systemd_networkd_network" {
  type      = string
  sensitive = true
}