variable "account_id" {
  type      = string
  sensitive = true
}

variable "zone_id" {
  type      = string
  sensitive = true
}

variable "k8s_nodes" {
  type      = map(string)
  sensitive = true
}

variable "k8s_controlplane_host" {
  type = string
}