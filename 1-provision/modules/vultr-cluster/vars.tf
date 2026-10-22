variable "instance_map" {
  type = map(object({
    region = string
    plan   = string
  }))
  description = "Instance info to create"
}
variable "ssh_keys" {
  type = map(string)
}

variable "cloudflare_main_zone_id" {
  type        = string
  description = "Cloudflare zone id"
  sensitive   = true
}
