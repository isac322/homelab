data "cloudflare_api_token_permission_groups_list" "zone" {
  scope = "com.cloudflare.api.account.zone"
}

data "cloudflare_api_token_permission_groups_list" "account" {
  scope = "com.cloudflare.api.account"
}

data "cloudflare_zone" "flareway_e2e" {
  zone_id = var.cloudflare_main_zone_id
}

locals {
  # Zone-scoped permissions (e.g. "Zone Read", "DNS Write")
  zone_permission_groups = {
    for p in data.cloudflare_api_token_permission_groups_list.zone.result :
    p.name => p.id
  }

  # Account-scoped permissions (e.g. "Cloudflare Tunnel Write", "Account Settings Read")
  account_permission_groups = {
    for p in data.cloudflare_api_token_permission_groups_list.account.result :
    p.name => p.id
  }
}

resource "cloudflare_api_token" "k8s_external_dns" {
  name = "${var.k8s_cluster_name}_k8s_external_dns"

  policies = [
    {
      effect = "allow"
      permission_groups = [
        { id = local.zone_permission_groups["Zone Read"] },
        { id = local.zone_permission_groups["DNS Write"] },
      ]
      resources = jsonencode({
        "com.cloudflare.api.account.zone.*" = "*"
      })
    }
  ]
}

resource "cloudflare_api_token" "k8s_cert_manager_dns_challenge" {
  name = "${var.k8s_cluster_name}_k8s_cert_manager_dns_challenge"

  policies = [{
    effect = "allow"
    permission_groups = [
      { id = local.zone_permission_groups["Zone Read"] },
      { id = local.zone_permission_groups["DNS Write"] },
    ]
    resources = jsonencode({
      "com.cloudflare.api.account.zone.*" = "*"
    })
  }]
}

resource "cloudflare_api_token" "k8s_cloudflared_gateway" {
  name = "${var.k8s_cluster_name}_k8s_cloudflared_gateway"

  policies = [
    {
      effect = "allow"
      permission_groups = [
        { id = local.zone_permission_groups["DNS Write"] },
      ]
      resources = jsonencode({
        "com.cloudflare.api.account.zone.*" = "*"
      })
    },
    {
      effect = "allow"
      permission_groups = [
        { id = local.account_permission_groups["Cloudflare Tunnel Write"] },
      ]
      resources = jsonencode({
        "com.cloudflare.api.account.*" = "*"
      })
    }
  ]
}

# Flareway verifies credentials through /user/tokens/verify, so this must be a
# user-owned API token rather than an account-owned token. Account permissions
# apply across the existing bhyoo.com account; add new capabilities explicitly.
resource "cloudflare_api_token" "flareway_e2e" {
  name = "flareway_e2e_github_actions"

  policies = [
    {
      effect = "allow"
      permission_groups = [
        # Access application and policy lifecycle.
        { id = local.account_permission_groups["Access: Apps and Policies Write"] },
        { id = local.account_permission_groups["Access: Organizations, Identity Providers, and Groups Read"] },
        { id = local.account_permission_groups["Access: Service Tokens Write"] },

        # Public and private Tunnel routing.
        { id = local.account_permission_groups["Cloudflare Tunnel Write"] },
        { id = local.account_permission_groups["Cloudflare One Networks Write"] },
        { id = local.account_permission_groups["Zero Trust Read"] },

        # Device settings (TCP/UDP proxy), device profiles, registrations,
        # and Gateway policies for the private WARP e2e path.
        { id = local.account_permission_groups["Zero Trust Write"] },
      ]
      resources = jsonencode({
        "com.cloudflare.api.account.${data.cloudflare_zone.flareway_e2e.account.id}" = "*"
      })
    },
    {
      effect = "allow"
      permission_groups = [
        # Public hostname discovery and DNS record lifecycle.
        { id = local.zone_permission_groups["Zone Read"] },
        { id = local.zone_permission_groups["DNS Write"] },
      ]
      resources = jsonencode({
        "com.cloudflare.api.account.zone.${data.cloudflare_zone.flareway_e2e.id}" = "*"
      })
    },
  ]

  lifecycle {
    precondition {
      condition     = data.cloudflare_zone.flareway_e2e.account.id == var.cloudflare_account_id
      error_message = "cloudflare_main_zone_id must belong to cloudflare_account_id."
    }
  }
}
