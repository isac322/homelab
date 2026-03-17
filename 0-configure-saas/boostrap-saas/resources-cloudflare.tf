data "cloudflare_user" "me" {}

data "cloudflare_api_token_permission_groups_list" "user" {
  scope = "com.cloudflare.api.user"
}
data "cloudflare_api_token_permission_groups_list" "zone" {
  scope = "com.cloudflare.api.account.zone"
}

locals {
  user_permission_groups = {
    for p in data.cloudflare_api_token_permission_groups_list.user.result :
    p.name => p.id
  }
  zone_permission_groups = {
    for p in data.cloudflare_api_token_permission_groups_list.zone.result :
    p.name => p.id
  }
}

# Token allowed to create new tokens.
# Can only be used from specific ip range.
resource "cloudflare_api_token" "homelab_api_token_create" {
  name = "homelab_api_token_create"

  policies = [
    {
      effect = "allow"
      permission_groups = [
        { id = local.user_permission_groups["API Tokens Write"] },
      ]
      resources = jsonencode({
        "com.cloudflare.api.user.${data.cloudflare_user.me.id}" = "*"
      })
    },
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
