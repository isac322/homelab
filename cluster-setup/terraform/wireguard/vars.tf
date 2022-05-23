variable "interface_name" {
  type        = string
  description = "Network interface name for wireguard"
  default     = "wg0"
}
variable "ip_subnet_cidr" {
  type        = string
  description = "Subnet for VPN only for kubectl"
  default     = "10.222.0.0/24"
}
variable "server_port" {
  type        = number
  description = "Wireguard listening port"
  default     = 51820
}
variable "server_host" {
  type        = string
  description = "Public host of Wireguard server"
}
variable "worker_count" {
  type        = number
  description = "Number of worker to create client wireguard profile"
}
variable "non_workers" {
  type        = list(string)
  description = "Name of non worker clients. (e.g. Laptop of admin to access cluster using kubectl)"
}