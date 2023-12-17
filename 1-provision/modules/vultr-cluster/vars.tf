variable "instance_map" {
  type = map(object({
    region = string
    plan   = string
  }))
  description = "Instance info to create"
}
variable "vpc_network" {
  type = object({
    network = string
    prefix  = number
    region  = string
  })
}
variable "ssh_keys" {
  type = map(string)
}

variable "cloudflare_main_zone_id" {
  type        = string
  description = "Cloudflare zone id"
  sensitive   = true
}
variable "k8s_controlplane_host" {
  type = string
}