import {
  to = module.dns_secrets.postmark_domain.bhyoo
  id = "8036320"
}

import {
  to = module.dns_secrets.aws_ssm_parameter.hermes_isacmes_telegram_token[0]
  id = "/homelab/cluster/backbone/token/telegram/isacmes"
}

import {
  to = module.dns_secrets.aws_ssm_parameter.hermes_isacmes_jay_telegram_token[0]
  id = "/homelab/cluster/backbone/token/telegram/isacmes-jay"
}

import {
  to = module.dns_secrets.aws_ssm_parameter.github_app_id_arc_cc_lb[0]
  id = "/homelab/cluster/backbone/github-app/arc-cc-lb/id"
}

import {
  to = module.dns_secrets.aws_ssm_parameter.github_app_installation_id_arc_cc_lb[0]
  id = "/homelab/cluster/backbone/github-app/arc-cc-lb/installation-id"
}

import {
  to = module.dns_secrets.aws_ssm_parameter.github_app_private_key_arc_cc_lb[0]
  id = "/homelab/cluster/backbone/github-app/arc-cc-lb/private-key"
}
