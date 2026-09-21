resource "github_repository" "flareway" {
  name        = "flareway"
  description = "A Kubernetes operator for Cloudflare Tunnel, Access & WARP - Gateway API routing through an Envoy data plane, with no inbound ports or public IPs on the cluster."
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
  topics = [
    "kubernetes",
    "kubernetes-operator",
    "kubernetes-controller",
    "gateway-api",
    "ingress",
    "ingress-controller",
    "cloudflare",
    "cloudflare-tunnel",
    "cloudflare-access",
    "cloudflare-warp",
    "cloudflared",
    "zero-trust",
    "zero-trust-network-access",
    "envoy",
  ]
  web_commit_signoff_required = false

  security_and_analysis {
    secret_scanning {
      status = "enabled"
    }
    secret_scanning_push_protection {
      status = "enabled"
    }
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "github_repository_vulnerability_alerts" "flareway" {
  repository = github_repository.flareway.name
  enabled    = true
}

resource "github_repository_dependabot_security_updates" "flareway" {
  repository = github_repository.flareway.name
  enabled    = true
}

resource "github_actions_repository_permissions" "flareway" {
  repository           = github_repository.flareway.name
  enabled              = true
  allowed_actions      = "all"
  sha_pinning_required = false
}

resource "github_branch_protection" "flareway_main" {
  repository_id = github_repository.flareway.node_id
  pattern       = "main"

  enforce_admins                  = true
  required_linear_history         = true
  require_conversation_resolution = true
  allows_force_pushes             = false
  allows_deletions                = false
  lock_branch                     = false

  required_status_checks {
    strict = true
    contexts = [
      "Cloudflare SDK parity",
      "Container build and runtime",
      "Envoy component tests",
      "GatewayHTTP conformance",
      "Generation diff",
      "Lint",
      "Schema, build, Helm, and Kustomize",
      "Unit and envtest",
    ]
  }

  required_pull_request_reviews {
    required_approving_review_count = 0
    dismiss_stale_reviews           = false
    require_code_owner_reviews      = false
    require_last_push_approval      = false
  }
}

resource "github_repository_environment" "cloudflare_e2e" {
  repository          = github_repository.flareway.name
  environment         = "cloudflare-e2e"
  can_admins_bypass   = true
  prevent_self_review = false
  wait_timer          = 0
}

resource "github_repository_environment" "release" {
  repository          = github_repository.flareway.name
  environment         = "release"
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

# --- Flareway e2e Zero Trust bootstrap -------------------------------------
# Durable account-level Zero Trust configuration for the private WARP e2e
# path. Per-run objects (service tokens, app-scoped enrollment policies,
# custom device profiles, device registrations) are created and deleted by
# the e2e runner with FLAREWAY_E2E_CF_API_TOKEN; Terraform must not manage
# or clobber them. The runner discovers the WARP app via
# GET /access/apps?type=warp and the team name via the organization
# auth_domain, so no additional GitHub secrets/variables are required.

# Account-wide device settings singleton. Only the two proxy flags below are
# managed. The provider Update sends explicit nulls for attributes that are
# set in state but unset in config, and Read fills every field after the
# first apply, so ignore_changes pins all unmanaged attributes to their
# imported/current values instead of letting a later apply wipe them.
# The resource does not support terraform import; first apply is an upsert.
resource "cloudflare_zero_trust_device_settings" "flareway_e2e" {
  provider = cloudflare.flareway_e2e

  # Same account the e2e token is scoped to (zone's owning account).
  account_id = module.dns_secrets.flareway_e2e.account_id

  # Required for Gateway network policies on private WARP traffic.
  gateway_proxy_enabled     = true
  gateway_udp_proxy_enabled = true

  lifecycle {
    ignore_changes = [
      disable_for_time,
      external_emergency_signal_enabled,
      external_emergency_signal_fingerprint,
      external_emergency_signal_interval,
      external_emergency_signal_url,
      root_certificate_installation_enabled,
      use_zt_virtual_ip,
    ]
  }
}

resource "cloudflare_zero_trust_access_application" "flareway_e2e_warp_enrollment" {
  provider = cloudflare.flareway_e2e

  # Same account the e2e token is scoped to (zone's owning account).
  account_id       = module.dns_secrets.flareway_e2e.account_id
  name             = "Warp Login App"
  type             = "warp"
  session_duration = "24h"
  policies         = []

  lifecycle {
    ignore_changes = [policies]
  }
}
