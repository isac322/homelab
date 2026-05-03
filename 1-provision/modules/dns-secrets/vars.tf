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

variable "hindsight" {
  description = "Hindsight credentials. Pass null to skip provisioning Hindsight-related SSM parameters and IAM permissions."
  type = object({
    openai_api_key = string # embeddings
    gcp_sa_key     = string # reranker (Vertex AI Semantic Ranker)
    gemini_api_key = string # LLM (Google AI Studio)
  })
  sensitive = true
  default   = null
}
