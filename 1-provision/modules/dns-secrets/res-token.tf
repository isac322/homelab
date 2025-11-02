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


resource "cloudflare_api_token" "k8s_cert_manager_dns_challenge" {
  name = "${var.k8s_cluster_name}_k8s_cert_manager_dns_challenge"

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


resource "cloudflare_api_token" "k8s_cloudflared_operator" {
  name = "${var.k8s_cluster_name}_k8s_cloudflared_operator"

  policy {
    permission_groups = [
      data.cloudflare_api_token_permission_groups.all.account["Cloudflare Tunnel Write"],
      data.cloudflare_api_token_permission_groups.all.account["Account Settings Read"],
    ]
    resources = {
      "com.cloudflare.api.account.*" = "*"
    }
  }

  policy {
    permission_groups = [
      data.cloudflare_api_token_permission_groups.all.zone["DNS Write"],
    ]
    resources = {
      "com.cloudflare.api.account.zone.*" = "*"
    }
  }
}
