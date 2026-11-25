resource "random_password" "cpa_gateway_signing_secret" {
  length  = 64
  special = false
}

resource "cloudflare_zero_trust_access_service_token" "cpa_gateway" {
  provider = cloudflare.cpa_gateway

  account_id = var.cloudflare_account_id
  name       = "cpa-gateway-worker"
  duration   = "8760h"
}

resource "cloudflare_zero_trust_access_policy" "cpa_gateway_allow_worker" {
  provider = cloudflare.cpa_gateway

  account_id = var.cloudflare_account_id
  name       = "cpa-gateway-allow-worker"
  decision   = "non_identity"

  include = [{
    service_token = {
      token_id = cloudflare_zero_trust_access_service_token.cpa_gateway.id
    }
  }]
}

resource "cloudflare_zero_trust_access_application" "cpa_origin" {
  provider = cloudflare.cpa_gateway

  account_id                = var.cloudflare_account_id
  type                      = "self_hosted"
  name                      = "cpa-origin"
  domain                    = "cpa-origin.bhyoo.com"
  auto_redirect_to_identity = false
  app_launcher_visible      = false

  policies = [{
    id         = cloudflare_zero_trust_access_policy.cpa_gateway_allow_worker.id
    precedence = 1
  }]
}

resource "cloudflare_workers_script" "cpa_gateway" {
  provider = cloudflare.cpa_gateway

  account_id         = var.cloudflare_account_id
  script_name        = "cpa-gateway"
  main_module        = "worker.js"
  content_file       = "${path.module}/files/cpa-gateway-worker.js"
  content_sha256     = filesha256("${path.module}/files/cpa-gateway-worker.js")
  compatibility_date = "2026-01-01"

  bindings = [
    {
      name = "OIDC_AUDIENCE"
      type = "plain_text"
      text = "https://cpa-gw.bhyoo.com"
    },
    {
      name = "ALLOWED_OWNER_ID"
      type = "plain_text"
      text = "4602209"
    },
    {
      name = "ALLOWED_REPOS"
      type = "plain_text"
      text = "isac322/flareway"
    },
    {
      name = "ORIGIN_BASE_URL"
      type = "plain_text"
      text = "https://cpa-origin.bhyoo.com"
    },
    {
      name = "TOKEN_TTL_SECONDS"
      type = "plain_text"
      text = "2700"
    },
    {
      name = "TOKEN_SIGNING_SECRET"
      type = "secret_text"
      text = random_password.cpa_gateway_signing_secret.result
    },
    {
      name = "CF_ACCESS_CLIENT_ID"
      type = "secret_text"
      text = cloudflare_zero_trust_access_service_token.cpa_gateway.client_id
    },
    {
      name = "CF_ACCESS_CLIENT_SECRET"
      type = "secret_text"
      text = cloudflare_zero_trust_access_service_token.cpa_gateway.client_secret
    },
  ]
}

resource "cloudflare_workers_custom_domain" "cpa_gateway" {
  provider = cloudflare.cpa_gateway

  account_id = var.cloudflare_account_id
  zone_id    = var.cloudflare_main_zone_id
  hostname   = "cpa-gw.bhyoo.com"
  service    = cloudflare_workers_script.cpa_gateway.script_name
}
