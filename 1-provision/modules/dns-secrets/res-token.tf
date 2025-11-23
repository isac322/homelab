data "cloudflare_api_token_permission_groups_list" "zone" {
  scope = "com.cloudflare.api.account.zone"
}

data "cloudflare_api_token_permission_groups_list" "account" {
  scope = "com.cloudflare.api.account"
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
      resources = {
        "com.cloudflare.api.account.zone.*" = "*"
      }
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
    resources = {
      "com.cloudflare.api.account.zone.*" = "*"
    }
  }]
}

resource "cloudflare_api_token" "k8s_cloudflared_operator" {
  name = "${var.k8s_cluster_name}_k8s_cloudflared_operator"

  policies = [
    {
      effect = "allow"
      permission_groups = [
        { id = local.zone_permission_groups["DNS Write"] },
      ]
      resources = {
        "com.cloudflare.api.account.zone.*" = "*"
      }
    },
    {
      effect = "allow"
      permission_groups = [
        { id = local.account_permission_groups["Cloudflare Tunnel Write"] },
        { id = local.account_permission_groups["Account Settings Read"] },
      ]
      resources = {
        "com.cloudflare.api.account.*" = "*"
      }
    }
  ]
}
