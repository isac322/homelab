# Bootstrap external SaaS

This requires user interaction that preparing access credentials for external SaaS.

Provide local values through an ignored `.tfvars` file. Grafana-managed
Telegram alerts require both values:

```hcl
grafana_telegram_bot_token = "<BotFather token>"
grafana_telegram_chat_id   = "-1001234567890"
```

ARC runners for `isac322/cc-lb` need a GitHub token with repository
Administration read/write (fine-grained) or classic `repo` scope:

```hcl
github_actions_pat_cc_lb = "<github token>"
```

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

