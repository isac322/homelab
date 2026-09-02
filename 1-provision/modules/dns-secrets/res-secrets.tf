resource "aws_ssm_parameter" "cf_api_token_for_external_dns" {
  name        = "/homelab/cluster/${var.k8s_cluster_name}/token/cloudflare/external-dns"
  description = "Cloudflare API token for external-dns"
  type        = "SecureString"
  value       = cloudflare_api_token.k8s_external_dns.value
}

resource "aws_ssm_parameter" "cf_api_token_for_cert_manager_dns_challenge" {
  name        = "/homelab/cluster/${var.k8s_cluster_name}/token/cloudflare/cert-manager-dns-challenge"
  description = "Cloudflare API token for dns-challenge of cert-manager"
  type        = "SecureString"
  value       = cloudflare_api_token.k8s_cert_manager_dns_challenge.value
}

resource "aws_ssm_parameter" "cf_api_token_for_cloudflared_gateway" {
  name        = "/homelab/cluster/${var.k8s_cluster_name}/token/cloudflare/cloudflared-gateway"
  description = "Cloudflare API token for cloudflared-gateway"
  type        = "SecureString"
  value       = cloudflare_api_token.k8s_cloudflared_gateway.value
}

resource "aws_ssm_parameter" "postmark_smtp_token_for_immich" {
  name        = "/homelab/cluster/${var.k8s_cluster_name}/token/postmark/immich-smtp"
  description = "Postmark SMTP token for Immich"
  type        = "SecureString"
  value       = one(postmark_server.immich.api_tokens)
}

resource "aws_ssm_parameter" "cf_account_id" {
  name        = "/homelab/cluster/${var.k8s_cluster_name}/cloudflare/account-id"
  description = "Cloudflare Account ID"
  type        = "String"
  value       = var.cloudflare_account_id
}

resource "tls_private_key" "democratic_csi" {
  count     = var.use_democratic_csi ? 1 : 0
  algorithm = "ED25519"
}

resource "aws_ssm_parameter" "democratic_csi_ssh_private_key" {
  count       = var.use_democratic_csi ? 1 : 0
  name        = "/homelab/cluster/${var.k8s_cluster_name}/ssh/democratic-csi/private-key"
  description = "SSH private key for Democratic CSI"
  type        = "SecureString"
  value       = tls_private_key.democratic_csi[0].private_key_openssh
}

# --- Hindsight agent memory server ---

resource "aws_ssm_parameter" "hindsight_openai_api_key" {
  count       = var.openai_api_key == null ? 0 : 1
  name        = "/homelab/cluster/${var.k8s_cluster_name}/token/openai/hindsight-embeddings"
  description = "OpenAI API key for Hindsight embeddings (text-embedding-3-large)"
  type        = "SecureString"
  value       = var.openai_api_key
}

resource "aws_ssm_parameter" "hindsight_gcp_sa_key" {
  count       = var.gcp_vertex_ai_sa_key == null ? 0 : 1
  name        = "/homelab/cluster/${var.k8s_cluster_name}/hindsight/gcp-vertex-ai-sa-key"
  description = "GCP Service Account key JSON for Vertex AI access (Hindsight reranker)"
  type        = "SecureString"
  value       = var.gcp_vertex_ai_sa_key
}

resource "aws_ssm_parameter" "hindsight_gemini_api_key" {
  count       = var.gemini_api_key == null ? 0 : 1
  name        = "/homelab/cluster/${var.k8s_cluster_name}/token/google/hindsight-llm"
  description = "Google AI Studio (Gemini) API key for Hindsight LLM"
  type        = "SecureString"
  value       = var.gemini_api_key
}

# --- Hermes agents ---

resource "aws_ssm_parameter" "hermes_openai_proxy" {
  count       = var.openai_proxy == null ? 0 : 1
  name        = "/homelab/cluster/${var.k8s_cluster_name}/proxy/cliproxyapi/hermes"
  description = "Shared CLIProxyAPI credentials for Hermes agents"
  type        = "SecureString"
  value = jsonencode({
    apiKey  = var.openai_proxy.api_key
    baseUrl = var.openai_proxy.base_url
  })
}

resource "aws_ssm_parameter" "hermes_gemini_api_key" {
  count       = var.gemini_api_key == null ? 0 : 1
  name        = "/homelab/cluster/${var.k8s_cluster_name}/token/google/hermes"
  description = "Shared direct Gemini API key for Hermes agents"
  type        = "SecureString"
  value       = var.gemini_api_key
}

resource "aws_ssm_parameter" "grafana_telegram_bot_token" {
  count       = var.grafana_telegram_bot_token == null ? 0 : 1
  name        = "/homelab/cluster/${var.k8s_cluster_name}/token/telegram/grafana"
  description = "Telegram bot token for Grafana-managed alerts"
  type        = "SecureString"
  value       = var.grafana_telegram_bot_token
}

resource "aws_ssm_parameter" "grafana_telegram_chat_id" {
  count       = var.grafana_telegram_chat_id == null ? 0 : 1
  name        = "/homelab/cluster/${var.k8s_cluster_name}/chat-id/telegram/grafana-alerts"
  description = "Telegram group chat ID for Grafana-managed alerts"
  type        = "String"
  value       = var.grafana_telegram_chat_id
}

resource "aws_ssm_parameter" "hermes_isacmes_telegram_token" {
  count       = var.hermes_isacmes_telegram_token == null ? 0 : 1
  name        = "/homelab/cluster/${var.k8s_cluster_name}/token/telegram/isacmes"
  description = "Telegram bot token for the Isacmes Hermes instance"
  type        = "SecureString"
  value       = var.hermes_isacmes_telegram_token
}

resource "aws_ssm_parameter" "hermes_isacmes_jay_telegram_token" {
  count       = var.hermes_isacmes_jay_telegram_token == null ? 0 : 1
  name        = "/homelab/cluster/${var.k8s_cluster_name}/token/telegram/isacmes-jay"
  description = "Telegram bot token for the Isacmes Jay Hermes instance"
  type        = "SecureString"
  value       = var.hermes_isacmes_jay_telegram_token
}

resource "aws_ssm_parameter" "github_app_id_arc_cc_lb" {
  count       = var.github_app_id_arc_cc_lb == null ? 0 : 1
  name        = "/homelab/cluster/${var.k8s_cluster_name}/github-app/arc-cc-lb/id"
  description = "GitHub App id for ARC runners on isac322/cc-lb"
  type        = "String"
  value       = var.github_app_id_arc_cc_lb
}

resource "aws_ssm_parameter" "github_app_installation_id_arc_cc_lb" {
  count       = var.github_app_installation_id_arc_cc_lb == null ? 0 : 1
  name        = "/homelab/cluster/${var.k8s_cluster_name}/github-app/arc-cc-lb/installation-id"
  description = "GitHub App installation id for ARC runners on isac322/cc-lb"
  type        = "String"
  value       = var.github_app_installation_id_arc_cc_lb
}

resource "aws_ssm_parameter" "github_app_private_key_arc_cc_lb" {
  count       = var.github_app_private_key_arc_cc_lb == null ? 0 : 1
  name        = "/homelab/cluster/${var.k8s_cluster_name}/github-app/arc-cc-lb/private-key"
  description = "GitHub App private key for ARC runners on isac322/cc-lb"
  type        = "SecureString"
  value       = var.github_app_private_key_arc_cc_lb
}

# --- External Secrets IAM ---

resource "aws_iam_user" "external_secrets" {
  name = "${var.k8s_cluster_name}-external-secrets"
  path = "/homelab/sa/"
}
resource "aws_iam_user_policy" "secret_read" {
  name   = "secret_read"
  policy = data.aws_iam_policy_document.secret_read.json
  user   = aws_iam_user.external_secrets.name
}
data "aws_iam_policy_document" "secret_read" {
  statement {
    effect  = "Allow"
    actions = ["ssm:GetParameter"]
    resources = concat(
      [
        aws_ssm_parameter.cf_api_token_for_cert_manager_dns_challenge.arn,
        aws_ssm_parameter.cf_api_token_for_external_dns.arn,
        aws_ssm_parameter.cf_api_token_for_cloudflared_gateway.arn,
        aws_ssm_parameter.postmark_smtp_token_for_immich.arn,
        aws_ssm_parameter.cf_account_id.arn,
      ],
      var.use_democratic_csi ? [aws_ssm_parameter.democratic_csi_ssh_private_key[0].arn] : [],
      var.openai_api_key == null ? [] : [aws_ssm_parameter.hindsight_openai_api_key[0].arn],
      var.gcp_vertex_ai_sa_key == null ? [] : [aws_ssm_parameter.hindsight_gcp_sa_key[0].arn],
      var.gemini_api_key == null ? [] : [aws_ssm_parameter.hindsight_gemini_api_key[0].arn],
      var.openai_proxy == null ? [] : [aws_ssm_parameter.hermes_openai_proxy[0].arn],
      var.gemini_api_key == null ? [] : [aws_ssm_parameter.hermes_gemini_api_key[0].arn],
      var.grafana_telegram_bot_token == null ? [] : [aws_ssm_parameter.grafana_telegram_bot_token[0].arn],
      var.grafana_telegram_chat_id == null ? [] : [aws_ssm_parameter.grafana_telegram_chat_id[0].arn],
      var.hermes_isacmes_telegram_token == null ? [] : [aws_ssm_parameter.hermes_isacmes_telegram_token[0].arn],
      var.hermes_isacmes_jay_telegram_token == null ? [] : [aws_ssm_parameter.hermes_isacmes_jay_telegram_token[0].arn],
      var.github_app_id_arc_cc_lb == null ? [] : [aws_ssm_parameter.github_app_id_arc_cc_lb[0].arn],
      var.github_app_installation_id_arc_cc_lb == null ? [] : [aws_ssm_parameter.github_app_installation_id_arc_cc_lb[0].arn],
      var.github_app_private_key_arc_cc_lb == null ? [] : [aws_ssm_parameter.github_app_private_key_arc_cc_lb[0].arn],
    )
  }
}
resource "aws_iam_user_group_membership" "cf_origin_ca" {
  user   = aws_iam_user.external_secrets.name
  groups = [var.aws_iam_group_name_cf_origin_ca_cert_issuer]
}
resource "aws_iam_access_key" "external_secrets" {
  user = aws_iam_user.external_secrets.name
}
