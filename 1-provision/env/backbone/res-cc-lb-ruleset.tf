# Imported default-branch ruleset (id 17108968). Only the required status check
# contexts track cc-lb's current CI job names; enforcement, conditions, the
# deletion/non-fast-forward rules, and the absence of bypass actors match the
# live ruleset. A missing context blocks merges, so rename checks here in the
# same change that renames the producing job.
resource "github_repository_ruleset" "cc_lb_default" {
  name        = "default"
  repository  = github_repository.cc_lb.name
  target      = "branch"
  enforcement = "active"

  conditions {
    ref_name {
      include = ["~DEFAULT_BRANCH"]
      exclude = []
    }
  }

  rules {
    deletion         = true
    non_fast_forward = true

    required_status_checks {
      strict_required_status_checks_policy = true
      do_not_enforce_on_create             = true

      # GitHub Actions (app id 15368).
      required_check {
        context        = "fmt"
        integration_id = 15368
      }
      required_check {
        context        = "cargo-deny"
        integration_id = 15368
      }
      required_check {
        context        = "nextest-cov"
        integration_id = 15368
      }
      required_check {
        context        = "clippy (sqlite)"
        integration_id = 15368
      }
      required_check {
        context        = "clippy (postgres)"
        integration_id = 15368
      }
      required_check {
        context        = "e2e"
        integration_id = 15368
      }
      required_check {
        context        = "promtool"
        integration_id = 15368
      }
      required_check {
        context        = "guard crate versions"
        integration_id = 15368
      }
      required_check {
        context        = "positioning metadata parity"
        integration_id = 15368
      }
      required_check {
        context        = "verify server release artifacts"
        integration_id = 15368
      }

      # Issue-agent review App (haechibot, app id 5118831).
      required_check {
        context        = "issue-agent/review"
        integration_id = 5118831
      }
    }
  }

  lifecycle {
    prevent_destroy = true
  }
}
