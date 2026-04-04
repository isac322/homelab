variable "k8s_cluster_name" {
  type = string
}

variable "aws_iam_group_name_cf_origin_ca_cert_issuer" {
  type = string
}

variable "cloudflare_account_id" {
  description = "Cloudflare Account ID"
  type        = string
}

variable "use_democratic_csi" {
  description = "Whether to create SSH key for Democratic CSI"
  type        = bool
  default     = false
}

variable "hindsight_openai_api_key" {
  description = "OpenAI API key for Hindsight embeddings (text-embedding-3-large)"
  type        = string
  sensitive   = true
}

variable "hindsight_gcp_sa_key" {
  description = "GCP Service Account key JSON for Vertex AI access (Hindsight LLM)"
  type        = string
  sensitive   = true
}
