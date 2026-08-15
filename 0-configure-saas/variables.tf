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

variable "openai_api_key" {
  type      = string
  sensitive = true
}

variable "openai_proxy" {
  type = object({
    api_key  = string
    base_url = string
  })
  sensitive = true
}

variable "gemini_api_key" {
  type      = string
  sensitive = true
}

variable "gcp_vertex_ai_sa_key" {
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
