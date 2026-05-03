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

variable "hindsight" {
  description = "Hindsight agent memory server credentials. Set to null to disable Hindsight provisioning entirely; otherwise all fields are required."
  type = object({
    openai_api_key = string # embeddings (text-embedding-3-large)
    gcp_sa_key     = string # reranker auth (Vertex AI Semantic Ranker via LiteLLM SDK)
    gemini_api_key = string # LLM (Google AI Studio Gemini API)
  })
  sensitive = true
  default   = null
}