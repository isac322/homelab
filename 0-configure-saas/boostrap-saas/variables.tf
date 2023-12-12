variable "cloudflare_email" {
  type        = string
  description = "email address of cloudflare-global-api-key"
  sensitive   = true
}
variable "cloudflare_global_api_key" {
  type        = string
  description = "https://developers.cloudflare.com/fundamentals/api/get-started/keys/"
  sensitive   = true
  validation {
    condition     = length(var.cloudflare_global_api_key) > 0
    error_message = "requires non-zero cloudflare_global_api_key"
  }
}
variable "cloudflare_origin_ca_key" {
  type        = string
  description = "https://developers.cloudflare.com/fundamentals/api/get-started/ca-keys/"
  sensitive   = true
  validation {
    condition     = length(var.cloudflare_origin_ca_key) > 0
    error_message = "requires non-zero cloudflare_origin_ca_key"
  }
}

variable "vultr_personal_access_token" {
  type      = string
  sensitive = true
  validation {
    condition     = length(var.vultr_personal_access_token) > 0
    error_message = "requires non-zero vultr_personal_access_token"
  }
}

###

variable "aws_admin_account_id" {
  type = number
  validation {
    condition     = var.aws_admin_account_id > 0
    error_message = "requires non-zero aws_account_id"
  }
}
variable "aws_admin_family_name" {
  type = string
  validation {
    condition     = length(var.aws_admin_family_name) > 0
    error_message = "requires non-zero aws_admin_family_name"
  }
}
variable "aws_admin_given_name" {
  type = string
  validation {
    condition     = length(var.aws_admin_given_name) > 0
    error_message = "requires non-zero aws_admin_given_name"
  }
}
variable "aws_admin_user_name" {
  type = string
  validation {
    condition     = length(var.aws_admin_user_name) > 0
    error_message = "requires non-zero aws_admin_user_name"
  }
}
variable "aws_admin_email" {
  type = string
  validation {
    condition     = length(var.aws_admin_email) > 0
    error_message = "requires non-zero aws_admin_email"
  }
}

variable "cloudflare_main_domain" {
  type = string
  validation {
    condition     = length(var.cloudflare_main_domain) > 0
    error_message = "requires non-zero cloudflare_domain"
  }
}

variable "tfe_organization" {
  type = string
  validation {
    condition     = length(var.tfe_organization) > 0
    error_message = "requires non-zero tfe_organization"
  }
}
variable "tfe_email" {
  type = string
  validation {
    condition     = length(var.tfe_email) > 0
    error_message = "requires non-zero tfe_email"
  }
}