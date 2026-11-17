# Generate in the remote workspace: no operator-supplied sensitive variable is
# needed. Apply this before configuring API/client authentication consumers.
resource "random_password" "hindsight_api_key" {
  length  = 64
  special = false
}

resource "aws_ssm_parameter" "hindsight_api_key" {
  name        = "/homelab/cluster/${var.k8s_cluster_name}/token/hindsight/api"
  description = "Bearer token for the self-hosted Hindsight API and its authorized clients"
  type        = "SecureString"
  value       = random_password.hindsight_api_key.result
}
