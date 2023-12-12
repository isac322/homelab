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
  name = var.cloudflare_main_domain
}
resource "tfe_variable" "cf_main_zone_id" {
  key             = "cloudflare_main_zone_id"
  value           = data.cloudflare_zone.main.id
  category        = "terraform"
  sensitive       = true
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
