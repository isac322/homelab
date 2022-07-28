data "cloudflare_api_token_permission_groups" "zone" {}


resource "cloudflare_api_token" "k8s_external_dns" {
  name = "prod_k8s_external_dns"

  policy {
    permission_groups = [
      data.cloudflare_api_token_permission_groups.zone.permissions["Zone Read"],
      data.cloudflare_api_token_permission_groups.zone.permissions["DNS Write"],
    ]
    resources = {
      "com.cloudflare.api.account.${var.account_id}" = "*"
    }
  }
}


resource "cloudflare_api_token" "k8s_cert_manager" {
  name = "prod_k8s_cert_manager"

  policy {
    permission_groups = [
      data.cloudflare_api_token_permission_groups.zone.permissions["Zone Read"],
      data.cloudflare_api_token_permission_groups.zone.permissions["DNS Write"],
    ]
    resources = {
      "com.cloudflare.api.account.${var.account_id}" = "*"
    }
  }
}

resource "cloudflare_record" "node" {
  for_each = nonsensitive(var.k8s_nodes)

  zone_id = var.zone_id
  name    = each.key
  value   = each.value
  type    = "A"
  proxied = false
}

resource "cloudflare_record" "k8s_control_plane" {
  for_each = nonsensitive(var.k8s_nodes)

  zone_id = var.zone_id
  name    = var.k8s_controlplane_host
  value   = each.value
  type    = "A"
  proxied = false
}
