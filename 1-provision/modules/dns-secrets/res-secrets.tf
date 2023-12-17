resource "aws_ssm_parameter" "cf_api_token_for_external_dns" {
  name        = "/homelab/cluster/${var.k8s_cluster_name}/token/cloudflare/external-dns"
  description = "Cloudflare API token for external-dns"
  type        = "SecureString"
  value       = cloudflare_api_token.k8s_external_dns.value
}

resource "aws_ssm_parameter" "cf_api_token_for_cert_manager" {
  name        = "/homelab/cluster/${var.k8s_cluster_name}/token/cloudflare/cert-manager"
  description = "Cloudflare API token for cert-manager"
  type        = "SecureString"
  value       = cloudflare_api_token.k8s_cert_manager.value
}

resource "aws_iam_user" "external_secrets" {
  name = "external-secrets"
  path = "/homelab/cluster/${var.k8s_cluster_name}/sa/"
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
    resources = [
      aws_ssm_parameter.cf_api_token_for_cert_manager.arn,
      aws_ssm_parameter.cf_api_token_for_external_dns.arn,
    ]
  }
}
resource "aws_iam_user_group_membership" "cf_origin_ca" {
  user   = aws_iam_user.external_secrets.name
  groups = [var.aws_iam_group_name_cf_origin_ca_cert_issuer]
}
resource "aws_iam_access_key" "external_secrets" {
  user = aws_iam_user.external_secrets.name
}
