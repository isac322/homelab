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

variable "cloudflare_main_zone_id" {
  description = "Cloudflare zone ID for bhyoo.com"
  type        = string
}

variable "use_democratic_csi" {
  description = "Whether to create SSH key for Democratic CSI"
  type        = bool
  default     = false
}

variable "openai_api_key" {
  type      = string
  sensitive = true
  default   = null
}

variable "openai_proxy" {
  type = object({
    api_key  = string
    base_url = string
  })
  sensitive = true
  default   = null
}

variable "gemini_api_key" {
  type      = string
  sensitive = true
  default   = null
}

variable "gcp_vertex_ai_sa_key" {
  type      = string
  sensitive = true
  default   = null
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
  default   = null
}

variable "hermes_isacmes_jay_telegram_token" {
  type      = string
  sensitive = true
  default   = null
}

variable "github_actions_pat_cc_lb" {
  type      = string
  sensitive = true
  default   = null
}
