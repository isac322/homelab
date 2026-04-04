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
  name        = "/homelab/cluster/${var.k8s_cluster_name}/token/openai/hindsight-embeddings"
  description = "OpenAI API key for Hindsight embeddings (text-embedding-3-large)"
  type        = "SecureString"
  value       = var.hindsight_openai_api_key
}

resource "aws_ssm_parameter" "hindsight_gcp_sa_key" {
  name        = "/homelab/cluster/${var.k8s_cluster_name}/hindsight/gcp-vertex-ai-sa-key"
  description = "GCP Service Account key JSON for Vertex AI access (Hindsight LLM)"
  type        = "SecureString"
  value = var.hindsight_gcp_sa_key
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
        aws_ssm_parameter.cf_account_id.arn,
        aws_ssm_parameter.hindsight_openai_api_key.arn,
        aws_ssm_parameter.hindsight_gcp_sa_key.arn,
      ],
      var.use_democratic_csi ? [aws_ssm_parameter.democratic_csi_ssh_private_key[0].arn] : []
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
