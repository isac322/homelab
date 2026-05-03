variable "cloudflare_token_for_token_issuing" {
  type        = string
  description = "API token of Cloudflare. This token must have permission `DNS Write`, `API Tokens Write` and `Zone Read` at least. Follow https://developers.cloudflare.com/api/tokens/create/"
  sensitive   = true
}

variable "cloudflare_account_id" {
  type        = string
  description = "Cloudflare Account ID"
}

variable "aws_iam_group_name_cf_origin_ca_cert_issuer" {
  type = string
}

variable "hindsight" {
  description = "Hindsight agent memory server credentials. Set to null to skip provisioning."
  type = object({
    openai_api_key = string
    gcp_sa_key     = string
    gemini_api_key = string
  })
  sensitive = true
  default   = null
}
