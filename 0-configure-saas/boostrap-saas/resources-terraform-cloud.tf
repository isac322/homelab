resource "tfe_organization" "this" {
  allow_force_delete_workspaces = true
  collaborator_auth_policy      = "two_factor_mandatory"
  name                          = var.tfe_organization
  email                         = var.tfe_email
}

resource "tfe_workspace" "backbone" {
  name                = "homelab-backbone"
  description         = "backbone cluster of homelab"
  organization        = tfe_organization.this.name
  speculative_enabled = false
  terraform_version   = "1.15.8"
  project_id          = tfe_project.homelab.id
}

resource "tfe_workspace" "vultr" {
  name                = "homelab-vultr"
  description         = "vultr cluster of homelab"
  organization        = tfe_organization.this.name
  speculative_enabled = false
  project_id          = tfe_project.homelab.id
}

resource "tfe_project" "homelab" {
  name         = "homelab"
  organization = tfe_organization.this.name
}

################### variable set ###################

resource "tfe_variable_set" "aws" {
  name         = "aws-oidc"
  description  = "OIDC connection to AWS"
  organization = tfe_organization.this.name
}
resource "tfe_workspace_variable_set" "aws-to-backbone" {
  variable_set_id = tfe_variable_set.aws.id
  workspace_id    = tfe_workspace.backbone.id
}
resource "tfe_workspace_variable_set" "aws-to-vultr" {
  variable_set_id = tfe_variable_set.aws.id
  workspace_id    = tfe_workspace.vultr.id
}
resource "tfe_variable" "aws_env_enable" {
  key             = "TFC_AWS_PROVIDER_AUTH"
  value           = "true"
  category        = "env"
  variable_set_id = tfe_variable_set.aws.id
}
resource "tfe_variable" "aws_role_arn" {
  key             = "TFC_AWS_RUN_ROLE_ARN"
  value           = aws_iam_role.terraform-cloud-deployer.arn
  category        = "env"
  sensitive       = true
  variable_set_id = tfe_variable_set.aws.id
}

##

resource "tfe_variable_set" "aws_params" {
  name         = "aws-parameters"
  description  = "AWS related runtime parameters"
  organization = tfe_organization.this.name
}
resource "tfe_workspace_variable_set" "aws_param_to_backbone" {
  variable_set_id = tfe_variable_set.aws_params.id
  workspace_id    = tfe_workspace.backbone.id
}
resource "tfe_workspace_variable_set" "aws_param_to_vultr" {
  variable_set_id = tfe_variable_set.aws_params.id
  workspace_id    = tfe_workspace.vultr.id
}
resource "tfe_variable" "aws_iam_group_name_cf_origin_ca_cert_issuer" {
  key             = "aws_iam_group_name_cf_origin_ca_cert_issuer"
  value           = aws_iam_group.cf_origin_ca_cert_issuer.name
  category        = "terraform"
  variable_set_id = tfe_variable_set.aws_params.id
}

##

resource "tfe_variable_set" "cloudflare" {
  name         = "cloudflare-token"
  description  = "Managing Cloudflare tokens"
  organization = tfe_organization.this.name
}
resource "tfe_workspace_variable_set" "cf_to_backbone" {
  variable_set_id = tfe_variable_set.cloudflare.id
  workspace_id    = tfe_workspace.backbone.id
}
resource "tfe_workspace_variable_set" "cf_to_vultr" {
  variable_set_id = tfe_variable_set.cloudflare.id
  workspace_id    = tfe_workspace.vultr.id
}
resource "tfe_variable" "cf_token_generator" {
  key             = "cloudflare_token_for_token_issuing"
  value           = cloudflare_api_token.homelab_api_token_create.value
  category        = "terraform"
  sensitive       = true
  variable_set_id = tfe_variable_set.cloudflare.id
}
data "cloudflare_zone" "main" {
  filter = {
    name = var.cloudflare_main_domain
  }
}
resource "tfe_variable" "cf_main_zone_id" {
  key             = "cloudflare_main_zone_id"
  value           = data.cloudflare_zone.main.id
  category        = "terraform"
  sensitive       = true
  variable_set_id = tfe_variable_set.cloudflare.id
}
resource "tfe_variable" "cf_account_id" {
  key             = "cloudflare_account_id"
  value           = data.cloudflare_zone.main.account.id
  category        = "terraform"
  variable_set_id = tfe_variable_set.cloudflare.id
}

##

resource "tfe_variable_set" "vultr" {
  name         = "vultr-token"
  description  = "Managing Vultr resources"
  organization = tfe_organization.this.name
}
resource "tfe_workspace_variable_set" "vultr_pat_to_vultr" {
  variable_set_id = tfe_variable_set.vultr.id
  workspace_id    = tfe_workspace.vultr.id
}
resource "tfe_variable" "vultr_pat" {
  key             = "vultr_pat"
  value           = var.vultr_personal_access_token
  category        = "terraform"
  sensitive       = true
  variable_set_id = tfe_variable_set.vultr.id
}

##

resource "tfe_variable" "postmark_account_token" {
  key          = "postmark_account_token"
  value        = var.postmark_account_token
  category     = "terraform"
  sensitive    = true
  workspace_id = tfe_workspace.backbone.id
}

##

moved {
  from = tfe_variable.hindsight_openai_embeddings_api_key
  to   = tfe_variable.openai_api_key
}

moved {
  from = tfe_variable.hermes_openai_proxy
  to   = tfe_variable.openai_proxy
}

moved {
  from = tfe_variable.hermes_gemini_api_key
  to   = tfe_variable.gemini_api_key
}

moved {
  from = tfe_variable.hindsight_gcp_vertex_ai_sa_key
  to   = tfe_variable.gcp_vertex_ai_sa_key
}

resource "tfe_variable" "openai_api_key" {
  key          = "openai_api_key"
  value        = var.openai_api_key
  category     = "terraform"
  sensitive    = true
  workspace_id = tfe_workspace.backbone.id

  lifecycle {
    create_before_destroy = true
  }
}

resource "tfe_variable" "openai_proxy" {
  key          = "openai_proxy"
  value        = jsonencode(var.openai_proxy)
  category     = "terraform"
  hcl          = true
  sensitive    = true
  workspace_id = tfe_workspace.backbone.id

  lifecycle {
    create_before_destroy = true
  }
}

resource "tfe_variable" "gemini_api_key" {
  key          = "gemini_api_key"
  value        = var.gemini_api_key
  category     = "terraform"
  sensitive    = true
  workspace_id = tfe_workspace.backbone.id

  lifecycle {
    create_before_destroy = true
  }
}

resource "tfe_variable" "gcp_vertex_ai_sa_key" {
  key          = "gcp_vertex_ai_sa_key"
  value        = var.gcp_vertex_ai_sa_key
  category     = "terraform"
  sensitive    = true
  workspace_id = tfe_workspace.backbone.id

  lifecycle {
    create_before_destroy = true
  }
}

resource "tfe_variable" "grafana_telegram_bot_token" {
  key          = "grafana_telegram_bot_token"
  value        = var.grafana_telegram_bot_token
  category     = "terraform"
  sensitive    = true
  workspace_id = tfe_workspace.backbone.id
}

resource "tfe_variable" "grafana_telegram_chat_id" {
  key          = "grafana_telegram_chat_id"
  value        = var.grafana_telegram_chat_id
  category     = "terraform"
  workspace_id = tfe_workspace.backbone.id
}

resource "tfe_variable" "hermes_isacmes_telegram_token" {
  key          = "hermes_isacmes_telegram_token"
  value        = var.hermes_isacmes_telegram_token
  category     = "terraform"
  sensitive    = true
  workspace_id = tfe_workspace.backbone.id
}

resource "tfe_variable" "hermes_isacmes_jay_telegram_token" {
  key          = "hermes_isacmes_jay_telegram_token"
  value        = var.hermes_isacmes_jay_telegram_token
  category     = "terraform"
  sensitive    = true
  workspace_id = tfe_workspace.backbone.id
}
