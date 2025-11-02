variable "k8s_cluster_name" {
  type = string
}

variable "aws_iam_group_name_cf_origin_ca_cert_issuer" {
  type = string
}

variable "use_democratic_csi" {
  description = "Whether to create SSH key for Democratic CSI"
  type        = bool
  default     = false
}
