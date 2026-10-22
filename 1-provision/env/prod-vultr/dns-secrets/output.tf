output "external_secrets_access_key" {
  value = {
    id     = aws_iam_access_key.external_secrets.id
    secret = aws_iam_access_key.external_secrets.secret
  }
  sensitive = true
}

output "democratic_csi_ssh_public_key" {
  description = "The OpenSSH public key for Democratic CSI"
  value       = var.use_democratic_csi ? tls_private_key.democratic_csi[0].public_key_openssh : null
}
