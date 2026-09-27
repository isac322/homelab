resource "github_repository" "krema" {
  name         = "krema"
  description  = "A lightweight, high-performance dock for KDE Plasma 6 — spiritual successor to Latte Dock"
  homepage_url = "https://krema.bhyoo.com/"
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
  squash_merge_commit_title   = "COMMIT_OR_PR_TITLE"
  squash_merge_commit_message = "COMMIT_MESSAGES"
  topics = [
    "accessibility",
    "cpp",
    "dock",
    "kde",
    "kde-plasma",
    "kirigami",
    "latte-dock",
    "launcher",
    "layer-shell",
    "linux",
    "pipewire",
    "plasma-6",
    "qml",
    "qt6",
    "taskbar",
    "wayland",
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

resource "github_repository_vulnerability_alerts" "krema" {
  repository = github_repository.krema.name
  enabled    = true
}

resource "github_repository_dependabot_security_updates" "krema" {
  repository = github_repository.krema.name
  enabled    = true
}

resource "github_actions_repository_permissions" "krema" {
  repository           = github_repository.krema.name
  enabled              = true
  allowed_actions      = "all"
  sha_pinning_required = false
}

# github_repository_pages is used instead of the deprecated `pages` block on
# github_repository: the inline block does not send `cname` when enabling
# Pages (expandPagesUpdate vs EnablePages), so the custom domain would only be
# set on a second apply. build_type "workflow" deploys from GitHub Actions;
# `source` is only valid for the "legacy" build type.
resource "github_repository_pages" "krema" {
  repository = github_repository.krema.name
  build_type = "workflow"
  cname      = "krema.bhyoo.com"
}

# Manage the `github-pages` deployment environment explicitly. GitHub
# auto-created it with a custom branch policy allowing only `master` when
# Pages was enabled; the environment and its policy are adopted via the
# import blocks in imports.tf so this is a no-op until the deployment
# policy intentionally changes.
resource "github_repository_environment" "krema_github_pages" {
  repository          = github_repository.krema.name
  environment         = "github-pages"
  can_admins_bypass   = true
  prevent_self_review = false
  wait_timer          = 0

  deployment_branch_policy {
    protected_branches     = false
    custom_branch_policies = true
  }

  depends_on = [github_repository_pages.krema]
}

# GitHub auto-created a "master"-only deployment branch policy on the
# github-pages environment when Pages was enabled. Managing it keeps the
# deploy gate in code; it is adopted via the import blocks in imports.tf.
resource "github_repository_environment_deployment_policy" "krema_github_pages_master" {
  repository     = github_repository.krema.name
  environment    = github_repository_environment.krema_github_pages.environment
  branch_pattern = "master"
}
