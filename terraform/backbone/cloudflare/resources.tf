data "cloudflare_zone" "zone" {
  name = var.zone_name
}

data "cloudflare_api_token_permission_groups" "zone" {}


resource "cloudflare_api_token" "external_dns_api_token" {
  name = "k8s_backbone_external_dns_api_token"

  policy {
    permission_groups = [
      data.cloudflare_api_token_permission_groups.zone.permissions["Zone Read"],
      data.cloudflare_api_token_permission_groups.zone.permissions["DNS Write"],
    ]
    resources = {
      "com.cloudflare.api.account.zone.${data.cloudflare_zone.zone.id}" = "*"
    }
  }
}


resource "cloudflare_api_token" "cert_manager_api_token" {
  name = "k8s_backbone_cert_manager_api_token"

  policy {
    permission_groups = [
      data.cloudflare_api_token_permission_groups.zone.permissions["Zone Read"],
      data.cloudflare_api_token_permission_groups.zone.permissions["DNS Write"],
    ]
    resources = {
      "com.cloudflare.api.account.zone.${data.cloudflare_zone.zone.id}" = "*"
    }
  }
}