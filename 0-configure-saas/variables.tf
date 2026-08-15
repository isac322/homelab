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

variable "postmark_account_token" {
  type      = string
  sensitive = true
}

variable "hindsight_openai_embeddings_api_key" {
  type      = string
  sensitive = true
}

variable "hindsight_gcp_vertex_ai_sa_key" {
  type      = string
  sensitive = true
}

variable "hindsight_gemini_api_key" {
  type      = string
  sensitive = true
}

variable "hermes_openai_proxy" {
  type = object({
    api_key  = string
    base_url = string
  })
  sensitive = true
}

variable "hermes_gemini_api_key" {
  type      = string
  sensitive = true
}

variable "hermes_isacmes_telegram_token" {
  type      = string
  sensitive = true
}

variable "hermes_isacmes_jay_telegram_token" {
  type      = string
  sensitive = true
}
