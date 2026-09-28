resource "github_repository" "pillar_csi" {
  name         = "pillar-csi"
  description  = "One Kubernetes CSI driver for your ZFS and LVM pools, served over kernel NVMe-oF/TCP. iSCSI, NFS and SMB planned. No SSH, no host CLI tools."
  homepage_url = "https://pillar-csi.bhyoo.com"
  visibility   = "public"

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
    "bare-metal",
    "block-storage",
    "configfs",
    "csi-driver",
    "go",
    "helm-chart",
    "homelab",
    "k3s",
    "kubernetes",
    "kubernetes-storage",
    "lvm",
    "nvme-of",
    "nvme-tcp",
    "persistent-volumes",
    "self-hosted",
    "storage",
    "zfs",
    "zvol",
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

resource "github_repository_vulnerability_alerts" "pillar_csi" {
  repository = github_repository.pillar_csi.name
  enabled    = true
}

resource "github_repository_dependabot_security_updates" "pillar_csi" {
  repository = github_repository.pillar_csi.name
  enabled    = true
}

resource "github_actions_repository_permissions" "pillar_csi" {
  repository           = github_repository.pillar_csi.name
  enabled              = true
  allowed_actions      = "all"
  sha_pinning_required = false
}

# github_repository_pages is used instead of the deprecated `pages` block on
# github_repository: the inline block does not send `cname` when enabling
# Pages (expandPagesUpdate vs EnablePages), so the custom domain would only be
# set on a second apply. build_type "workflow" deploys from GitHub Actions;
# `source` is only valid for the "legacy" build type. Pages did not exist
# before Terraform, so this is created (not imported). Enabling Pages ahead of
# the first deploy is intended: actions/deploy-pages fails until it is enabled.
resource "github_repository_pages" "pillar_csi" {
  repository = github_repository.pillar_csi.name
  build_type = "workflow"
  cname      = "pillar-csi.bhyoo.com"
}

# Manage the `github-pages` deployment environment explicitly so the Pages
# deploy is limited to protected branches (master is protected by a ruleset).
# GitHub may auto-create it when Pages is enabled; the provider's create is a
# PUT upsert, so no import is needed.
resource "github_repository_environment" "pillar_csi_github_pages" {
  repository          = github_repository.pillar_csi.name
  environment         = "github-pages"
  can_admins_bypass   = true
  prevent_self_review = false
  wait_timer          = 0

  deployment_branch_policy {
    protected_branches     = true
    custom_branch_policies = false
  }

  depends_on = [github_repository_pages.pillar_csi]
}


# Expose the Cloudflare Web Analytics beacon token to the repo's Actions
# workflows so the site build can embed it (the record is DNS-only, so
# Cloudflare cannot inject the beacon). Requires `Variables` RW on the PAT,
# which it does not currently hold (Administration/Environments/Pages RW only).
resource "github_actions_variable" "pillar_csi_cf_web_analytics_token" {
  repository    = github_repository.pillar_csi.name
  variable_name = "CF_WEB_ANALYTICS_TOKEN"
  value         = cloudflare_web_analytics_site.pillar_csi.site_token
}