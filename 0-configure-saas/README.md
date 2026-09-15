# Bootstrap external SaaS

This requires user interaction that preparing access credentials for external SaaS.

Provide local values through an ignored `.tfvars` file. Grafana-managed
Telegram alerts require both values:

```hcl
grafana_telegram_bot_token = "<BotFather token>"
grafana_telegram_chat_id   = "-1001234567890"
```

ARC runners for `isac322/cc-lb` use a GitHub App. After creating and
installing the app on that repository, provide:

```hcl
github_app_id_arc_cc_lb              = "123456"
github_app_installation_id_arc_cc_lb = "12345678"
github_app_private_key_arc_cc_lb     = <<-EOT
-----BEGIN RSA PRIVATE KEY-----
...
-----END RSA PRIVATE KEY-----
EOT
```

The `homelab-backbone` workspace also needs a fine-grained GitHub PAT:

```hcl
github_personal_access_token = "<fine-grained PAT>"
```

Create it under the `isac322` resource owner, select only
`isac322/flareway`, and grant these repository permissions:

- `Administration`: Read and write
- `Environments`: Read and write

GitHub grants `Metadata: Read` automatically. `Contents`, `Actions`, and
`Workflows` write permissions are not required. The bootstrap configuration
stores this value as the sensitive Terraform variable
`github_personal_access_token` in the `bhyoo/homelab-backbone` HCP Terraform
workspace.

## Get credential

### AWS

#### Using SSO

`eval $(aws configure export-credentials --profile personal --format env)`

#### Root user

```Bash
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
export AWS_SESSION_TOKEN=...
```

### Terraform Cloud

https://registry.terraform.io/providers/hashicorp/tfe/latest/docs#authentication

