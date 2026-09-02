variable "cloudflare_token_for_token_issuing" {
  type        = string
  description = "API token of Cloudflare. This token must have permission `DNS Write`, `API Tokens Write` and `Zone Read` at least. Follow https://developers.cloudflare.com/api/tokens/create/"
  sensitive   = true
}

variable "cloudflare_account_id" {
  type        = string
  description = "Cloudflare Account ID"
}

variable "cloudflare_main_zone_id" {
  type        = string
  description = "Cloudflare zone ID for bhyoo.com"
}

variable "postmark_account_token" {
  type        = string
  description = "Postmark Account API token"
  sensitive   = true
}

variable "aws_iam_group_name_cf_origin_ca_cert_issuer" {
  type = string
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

variable "grafana_telegram_bot_token" {
  type      = string
  sensitive = true
  default   = null
}

variable "grafana_telegram_chat_id" {
  type    = string
  default = null

  validation {
    condition = (
      var.grafana_telegram_chat_id == null
      || can(regex("^-[0-9]+$", var.grafana_telegram_chat_id))
    )
    error_message = "grafana_telegram_chat_id must be a negative Telegram group or supergroup chat ID."
  }
}

variable "hermes_isacmes_telegram_token" {
  type      = string
  sensitive = true
}

variable "hermes_isacmes_jay_telegram_token" {
  type      = string
  sensitive = true
}

variable "github_actions_pat_cc_lb" {
  type      = string
  sensitive = true
  default   = null
}
