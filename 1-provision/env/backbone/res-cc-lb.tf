locals {
  cc_lb_pages_cname             = "cc-lb.bhyoo.com"
  cc_lb_fork_pr_approval_policy = "all_external_contributors"

  # Staged HTTPS bootstrap. Keep false for the first apply, which creates DNS
  # and Pages. GitHub only issues the custom-domain certificate after the DNS
  # record resolves and the domain check passes; enforcing HTTPS before then
  # fails. Set to true in a follow-up change once the Pages settings report an
  # approved certificate for cc_lb_pages_cname, then apply again.
  cc_lb_pages_https_enforced = true
}

resource "github_repository" "cc_lb" {
  name         = "cc-lb"
  description  = "Self-hosted Anthropic-compatible reverse proxy and load balancer for pooled API-key and OAuth upstreams."
  homepage_url = "https://${local.cc_lb_pages_cname}/"
  visibility   = "public"

  has_issues      = true
  has_projects    = false
  has_wiki        = false
  has_discussions = true
  is_template     = false

  allow_squash_merge          = true
  allow_merge_commit          = false
  allow_rebase_merge          = false
  allow_auto_merge            = false
  allow_update_branch         = true
  delete_branch_on_merge      = true
  squash_merge_commit_title   = "COMMIT_OR_PR_TITLE"
  squash_merge_commit_message = "COMMIT_MESSAGES"
  # Description and shipped-only topics follow cc-lb's positioning.yml.
  topics = [
    "anthropic",
    "load-balancer",
    "reverse-proxy",
    "rust",
    "wasmtime",
  ]
  web_commit_signoff_required = false

  lifecycle {
    prevent_destroy = true
  }
}

# Provider 6.13.0 updates security settings before repository visibility.
# Enabling secret scanning while this repository is still private returns 422.
# Apply both protections only after the public visibility change has completed.
resource "terraform_data" "cc_lb_secret_scanning" {
  triggers_replace = [
    github_repository.cc_lb.id,
    github_repository.cc_lb.visibility,
  ]

  depends_on = [github_repository.cc_lb]

  provisioner "local-exec" {
    command = <<-EOT
      curl --fail --silent --show-error --output /dev/null -X PATCH \
        -H "Authorization: Bearer $GITHUB_TOKEN" \
        -H "Accept: application/vnd.github+json" \
        -H "X-GitHub-Api-Version: 2022-11-28" \
        "https://api.github.com/repos/isac322/$REPO" \
        -d '{"security_and_analysis":{"secret_scanning":{"status":"enabled"},"secret_scanning_push_protection":{"status":"enabled"}}}'
    EOT

    environment = {
      GITHUB_TOKEN = var.github_personal_access_token
      REPO         = github_repository.cc_lb.name
    }
  }
}

resource "github_repository_vulnerability_alerts" "cc_lb" {
  repository = github_repository.cc_lb.name
  enabled    = true
}

resource "github_repository_dependabot_security_updates" "cc_lb" {
  repository = github_repository.cc_lb.name
  enabled    = true

  depends_on = [github_repository_vulnerability_alerts.cc_lb]
}

resource "github_actions_repository_permissions" "cc_lb" {
  repository           = github_repository.cc_lb.name
  enabled              = true
  allowed_actions      = "all"
  sha_pinning_required = false
}

# Provider 6.13.0 does not expose fork PR workflow approval settings. Require
# maintainer approval for every external contributor through the REST endpoint.
resource "terraform_data" "cc_lb_fork_pr_contributor_approval" {
  triggers_replace = [
    github_repository.cc_lb.id,
    github_repository.cc_lb.visibility,
    local.cc_lb_fork_pr_approval_policy,
  ]

  depends_on = [github_actions_repository_permissions.cc_lb]

  provisioner "local-exec" {
    command = <<-EOT
      curl --fail-with-body --silent --show-error -X PUT \
        -H "Authorization: Bearer $GITHUB_TOKEN" \
        -H "Accept: application/vnd.github+json" \
        -H "X-GitHub-Api-Version: 2022-11-28" \
        "https://api.github.com/repos/isac322/$REPO/actions/permissions/fork-pr-contributor-approval" \
        -d "{\"approval_policy\":\"$APPROVAL_POLICY\"}"
    EOT

    environment = {
      GITHUB_TOKEN    = var.github_personal_access_token
      REPO            = github_repository.cc_lb.name
      APPROVAL_POLICY = local.cc_lb_fork_pr_approval_policy
    }
  }
}

# The GitHub provider has no private-vulnerability-reporting resource. Use the
# idempotent repository endpoint until the provider exposes this setting.
resource "terraform_data" "cc_lb_private_vulnerability_reporting" {
  triggers_replace = [
    github_repository.cc_lb.id,
    github_repository.cc_lb.visibility,
  ]

  provisioner "local-exec" {
    command = <<-EOT
      curl --fail-with-body --silent --show-error -X PUT \
        -H "Authorization: Bearer $GITHUB_TOKEN" \
        -H "Accept: application/vnd.github+json" \
        -H "X-GitHub-Api-Version: 2022-11-28" \
        "https://api.github.com/repos/isac322/$REPO/private-vulnerability-reporting"
    EOT

    environment = {
      GITHUB_TOKEN = var.github_personal_access_token
      REPO         = github_repository.cc_lb.name
    }
  }
}

# Use the standalone Pages resource, not the deprecated repository pages block.
# Workflow builds deploy from the repository's GitHub Actions workflow; source
# is only valid for legacy builds. Provider 6.13.0 can initially record an empty
# cname after EnablePages, so bootstrap may need a second Pages apply to set it.
resource "github_repository_pages" "cc_lb" {
  repository = github_repository.cc_lb.name
  build_type = "workflow"
  cname      = local.cc_lb_pages_cname

  depends_on = [
    github_actions_repository_permissions.cc_lb,
    cloudflare_dns_record.cc_lb_pages,
  ]
}

# Provider 6.13.0 sends cname=null for an https_enforced-only Pages update,
# clearing the domain. As with Flareway, send both fields in one request instead.
# Gated by local.cc_lb_pages_https_enforced, the same count-on-a-local switch
# used for staged records elsewhere, so the first apply skips this step.
resource "terraform_data" "cc_lb_pages_https" {
  count = local.cc_lb_pages_https_enforced ? 1 : 0

  triggers_replace = [
    github_repository_pages.cc_lb.id,
    github_repository_pages.cc_lb.cname,
  ]

  provisioner "local-exec" {
    command = <<-EOT
      curl --fail-with-body --silent --show-error -X PUT \
        -H "Authorization: Bearer $GITHUB_TOKEN" \
        -H "Accept: application/vnd.github+json" \
        -H "X-GitHub-Api-Version: 2022-11-28" \
        "https://api.github.com/repos/isac322/$REPO/pages" \
        -d "{\"cname\":\"$CNAME\",\"https_enforced\":true}"
    EOT

    environment = {
      GITHUB_TOKEN = var.github_personal_access_token
      REPO         = github_repository.cc_lb.name
      CNAME        = local.cc_lb_pages_cname
    }
  }
}
