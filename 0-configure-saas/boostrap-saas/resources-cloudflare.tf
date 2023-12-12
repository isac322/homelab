data "cloudflare_user" "me" {}
data "cloudflare_api_token_permission_groups" "all" {}

# Token allowed to create new tokens.
# Can only be used from specific ip range.
resource "cloudflare_api_token" "homelab_api_token_create" {
  name = "homelab_api_token_create"

  policy {
    permission_groups = [
      data.cloudflare_api_token_permission_groups.all.user["API Tokens Write"],
    ]
    resources = {
      "com.cloudflare.api.user.${data.cloudflare_user.me.id}" = "*"
    }
  }

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