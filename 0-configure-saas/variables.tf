variable "cloudflare_email" {
  type      = string
  sensitive = true
}
variable "cloudflare_global_api_key" {
  type      = string
  sensitive = true
}
variable "cloudflare_origin_ca_key" {
  type      = string
  sensitive = true
}

variable "vultr_personal_access_token" {
  type      = string
  sensitive = true
}

variable "hindsight_openai_api_key" {
  description = "OpenAI API key for Hindsight embeddings"
  type        = string
  sensitive   = true
}

variable "hindsight_gcp_sa_key" {
  description = "GCP Service Account key JSON for Vertex AI (Hindsight LLM)"
  type        = string
  sensitive   = true
}