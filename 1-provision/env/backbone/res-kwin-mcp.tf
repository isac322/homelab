resource "github_repository" "kwin_mcp" {
  name         = "kwin-mcp"
  description  = "MCP server for Linux desktop GUI automation on KDE Plasma 6 Wayland — 29 tools for virtual and live sessions"
  homepage_url = "https://pypi.org/project/kwin-mcp/"
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
    "ai-agents",
    "at-spi2",
    "claude-code",
    "desktop-automation",
    "e2e-testing",
    "gui-automation",
    "headless-testing",
    "kde",
    "kwin",
    "libei",
    "linux",
    "live-desktop",
    "live-session",
    "mcp",
    "mcp-server",
    "model-context-protocol",
    "plasma",
    "python",
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

resource "github_repository_vulnerability_alerts" "kwin_mcp" {
  repository = github_repository.kwin_mcp.name
  enabled    = true
}

resource "github_repository_dependabot_security_updates" "kwin_mcp" {
  repository = github_repository.kwin_mcp.name
  enabled    = true
}

resource "github_actions_repository_permissions" "kwin_mcp" {
  repository           = github_repository.kwin_mcp.name
  enabled              = true
  allowed_actions      = "all"
  sha_pinning_required = false
}

resource "github_repository_environment" "kwin_mcp_github_pages" {
  repository          = github_repository.kwin_mcp.name
  environment         = "github-pages"
  can_admins_bypass   = true
  prevent_self_review = false
  wait_timer          = 0

  deployment_branch_policy {
    protected_branches     = false
    custom_branch_policies = true
  }
}

resource "github_repository_environment_deployment_policy" "kwin_mcp_github_pages_gh_pages" {
  repository     = github_repository.kwin_mcp.name
  environment    = github_repository_environment.kwin_mcp_github_pages.environment
  branch_pattern = "gh-pages"
}

resource "github_repository_environment_deployment_policy" "kwin_mcp_github_pages_main" {
  repository     = github_repository.kwin_mcp.name
  environment    = github_repository_environment.kwin_mcp_github_pages.environment
  branch_pattern = "main"
}

resource "github_repository_environment" "kwin_mcp_pypi" {
  repository          = github_repository.kwin_mcp.name
  environment         = "pypi"
  can_admins_bypass   = true
  prevent_self_review = false
  wait_timer          = 0
}

resource "github_repository_ruleset" "kwin_mcp_default" {
  name        = "main"
  repository  = github_repository.kwin_mcp.name
  target      = "branch"
  enforcement = "active"

  bypass_actors {
    actor_id    = 5
    actor_type  = "RepositoryRole"
    bypass_mode = "always"
  }

  conditions {
    ref_name {
      include = ["~DEFAULT_BRANCH"]
      exclude = []
    }
  }

  rules {
    deletion                = true
    non_fast_forward        = true
    required_linear_history = true

    pull_request {
      allowed_merge_methods             = ["squash"]
      dismiss_stale_reviews_on_push     = true
      require_code_owner_review         = false
      require_last_push_approval        = true
      required_approving_review_count   = 1
      required_review_thread_resolution = false
    }

    required_status_checks {
      strict_required_status_checks_policy = true
      do_not_enforce_on_create             = false

      required_check {
        context        = "lint (3.12)"
        integration_id = 15368
      }
      required_check {
        context        = "lint (3.13)"
        integration_id = 15368
      }
      required_check {
        context        = "build"
        integration_id = 15368
      }
      required_check {
        context        = "type-check"
        integration_id = 15368
      }
      required_check {
        context        = "lint (3.14)"
        integration_id = 15368
      }
      required_check {
        context        = "lint (3.15)"
        integration_id = 15368
      }
      required_check {
        context        = "issue-agent/review"
        integration_id = 5118831
      }
      required_check {
        context        = "Virtual KWin session (amd64)"
        integration_id = 15368
      }
      required_check {
        context        = "Virtual KWin session (arm64)"
        integration_id = 15368
      }
      required_check {
        context        = "Virtual KWin session (fedora-amd64)"
        integration_id = 15368
      }
      required_check {
        context        = "Virtual KWin session (fedora-arm64)"
        integration_id = 15368
      }
      required_check {
        context        = "Virtual KWin session (opensuse-amd64)"
        integration_id = 15368
      }
      required_check {
        context        = "Virtual KWin session (opensuse-arm64)"
        integration_id = 15368
      }
      required_check {
        context        = "Virtual KWin session (archlinux-amd64)"
        integration_id = 15368
      }
    }
  }

  lifecycle {
    prevent_destroy = true
  }
}
