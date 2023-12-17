data "cloudflare_api_token_permission_groups" "all" {}


resource "cloudflare_api_token" "k8s_external_dns" {
  name = "${var.k8s_cluster_name}_k8s_external_dns"

  policy {
    permission_groups = [
      data.cloudflare_api_token_permission_groups.all.zone["Zone Read"],
      data.cloudflare_api_token_permission_groups.all.zone["DNS Write"],
    ]
    resources = {
      "com.cloudflare.api.account.zone.*" = "*"
    }
  }
}


resource "cloudflare_api_token" "k8s_cert_manager" {
  name = "${var.k8s_cluster_name}_k8s_cert_manager"

  policy {
    permission_groups = [
      data.cloudflare_api_token_permission_groups.all.zone["Zone Read"],
      data.cloudflare_api_token_permission_groups.all.zone["DNS Write"],
    ]
    resources = {
      "com.cloudflare.api.account.zone.*" = "*"
    }
  }
}
