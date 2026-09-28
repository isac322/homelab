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

variable "github_personal_access_token" {
  type        = string
  description = <<-EOT
    Fine-grained GitHub PAT used to manage the isac322/flareway, isac322/krema, and isac322/pillar-csi
    repositories, their GitHub Pages sites, their github-pages deployment
    environments, flareway's cloudflare-e2e and release environments, and the
    cloudflare-e2e environment's Actions secrets on isac322/flareway.
    Resource owner: isac322.
    Repository permissions: Administration, Read and write; Environments, Read and write;
    Pages, Read and write.
    Metadata Read is granted automatically; no Contents or Actions Write permission is required.
    Because all repositories already exist and are imported, Repository access may select
    only isac322/flareway, isac322/krema, and isac322/pillar-csi.
    A bootstrap token that creates a not-yet-existing repository must temporarily use
    All repositories; rotate it to an only-selected-repository token after creation.
  EOT
  sensitive   = true
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

variable "hermes_yjyou_telegram_token" {
  type      = string
  sensitive = true
  default   = null
}

variable "github_app_id_arc_cc_lb" {
  type    = string
  default = null
}

variable "github_app_installation_id_arc_cc_lb" {
  type    = string
  default = null
}

variable "github_app_private_key_arc_cc_lb" {
  type      = string
  sensitive = true
  default   = null
}
