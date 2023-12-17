variable "cloudflare_token_for_token_issuing" {
  type        = string
  description = "API token of Cloudflare. This token must have permission `DNS Write`, `API Tokens Write` and `Zone Read` at least. Follow https://developers.cloudflare.com/api/tokens/create/"
  sensitive   = true
}

variable "aws_iam_group_name_cf_origin_ca_cert_issuer" {
  type = string
}
