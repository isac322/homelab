data "cloudflare_api_token_permission_groups" "zone" {}


resource "cloudflare_api_token" "k8s_external_dns" {
  name = "backbone_k8s_external_dns"

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
  name = "backbone_k8s_cert_manager"

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