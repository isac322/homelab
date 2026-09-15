resource "github_repository" "flareway" {
  name        = "flareway"
  description = "Cloudflare networking and Zero Trust for Kubernetes"
  visibility  = "public"

  has_issues      = true
  has_projects    = false
  has_wiki        = false
  has_discussions = false
  is_template     = false

  allow_squash_merge          = true
  allow_merge_commit          = false
  allow_rebase_merge          = false
  allow_auto_merge            = true
  allow_update_branch         = true
  delete_branch_on_merge      = true
  squash_merge_commit_title   = "PR_TITLE"
  squash_merge_commit_message = "COMMIT_MESSAGES"
  topics                      = []
  web_commit_signoff_required = false

  lifecycle {
    prevent_destroy = true
  }
}

resource "github_repository_vulnerability_alerts" "flareway" {
  repository = github_repository.flareway.name
  enabled    = true
}

resource "github_repository_environment" "cloudflare_e2e" {
  repository          = github_repository.flareway.name
  environment         = "cloudflare-e2e"
  can_admins_bypass   = true
  prevent_self_review = false
  wait_timer          = 0
}

resource "github_actions_environment_secret" "flareway_e2e_api_token" {
  repository  = github_repository.flareway.name
  environment = github_repository_environment.cloudflare_e2e.environment
  secret_name = "FLAREWAY_E2E_CF_API_TOKEN"
  value       = module.dns_secrets.flareway_e2e.api_token
}

resource "github_actions_environment_secret" "flareway_e2e_account_id" {
  repository  = github_repository.flareway.name
  environment = github_repository_environment.cloudflare_e2e.environment
  secret_name = "FLAREWAY_E2E_CF_ACCOUNT_ID"
  value       = module.dns_secrets.flareway_e2e.account_id
}

resource "github_actions_environment_secret" "flareway_e2e_zone" {
  repository  = github_repository.flareway.name
  environment = github_repository_environment.cloudflare_e2e.environment
  secret_name = "FLAREWAY_E2E_ZONE"
  value       = module.dns_secrets.flareway_e2e.zone
}
