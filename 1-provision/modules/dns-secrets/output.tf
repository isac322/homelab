output "external_secrets_access_key" {
  value = {
    id     = aws_iam_access_key.external_secrets.id
    secret = aws_iam_access_key.external_secrets.secret
  }
  sensitive = true
}
