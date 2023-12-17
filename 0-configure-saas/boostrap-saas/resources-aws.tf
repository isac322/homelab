data "aws_ssoadmin_instances" "instance" {}

################### SSO ###################

resource "aws_ssoadmin_permission_set" "AdministratorAccess" {
  name             = "AdministratorAccess"
  instance_arn     = tolist(data.aws_ssoadmin_instances.instance.arns)[0]
  session_duration = "PT12H"
}

resource "aws_ssoadmin_managed_policy_attachment" "AdministratorAccess" {
  instance_arn       = tolist(data.aws_ssoadmin_instances.instance.arns)[0]
  managed_policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
  permission_set_arn = aws_ssoadmin_permission_set.AdministratorAccess.arn
}

resource "aws_identitystore_user" "admin" {
  identity_store_id = tolist(data.aws_ssoadmin_instances.instance.identity_store_ids)[0]

  display_name = join(" ", [var.aws_admin_given_name, var.aws_admin_family_name])
  user_name    = var.aws_admin_user_name

  name {
    family_name = var.aws_admin_family_name
    given_name  = var.aws_admin_given_name
  }

  emails {
    value   = var.aws_admin_email
    primary = true
    type    = "work"
  }
}

resource "aws_ssoadmin_account_assignment" "admin" {
  instance_arn       = tolist(data.aws_ssoadmin_instances.instance.arns)[0]
  permission_set_arn = aws_ssoadmin_permission_set.AdministratorAccess.arn

  principal_id   = aws_identitystore_user.admin.user_id
  principal_type = "USER"

  target_id   = var.aws_admin_account_id
  target_type = "AWS_ACCOUNT"
}

################### OIDC ###################

resource "aws_iam_openid_connect_provider" "terraform-cloud" {
  url             = "https://app.terraform.io"
  client_id_list  = ["aws.workload.identity"]
  thumbprint_list = ["9e99a48a9960b14926bb7f3b02e22da2b0ab7280"]
}

resource "aws_iam_role" "terraform-cloud-deployer" {
  name               = "terraform-cloud-deployer"
  path               = "/cicd/"
  assume_role_policy = data.aws_iam_policy_document.terraform-cloud-deployer-assume-role-policy.json

  inline_policy {
    name   = "resource-manager"
    policy = data.aws_iam_policy_document.terraform-cloud-deployer-policy.json
  }
}
data "aws_iam_policy_document" "terraform-cloud-deployer-assume-role-policy" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.terraform-cloud.arn]
    }

    condition {
      test     = "StringEquals"
      values   = ["aws.workload.identity"]
      variable = "app.terraform.io:aud"
    }

    condition {
      test = "StringLike"
      values = [
        "organization:${tfe_organization.this.name}:project:${tfe_project.homelab.name}:workspace:${tfe_workspace.backbone.name}:run_phase:*",
        "organization:${tfe_organization.this.name}:project:${tfe_project.homelab.name}:workspace:${tfe_workspace.vultr.name}:run_phase:*",
      ]
      variable = "app.terraform.io:sub"
    }
  }
}
data "aws_iam_policy_document" "terraform-cloud-deployer-policy" {
  statement {
    effect = "Allow"
    actions = [
      "iam:AddUserToGroup",
      "iam:RemoveUserFromGroup",
    ]
    resources = [aws_iam_group.cf_origin_ca_cert_issuer.arn]
  }

  statement {
    effect = "Allow"
    actions = [
      "iam:CreateUser",
      "iam:GetUser",
      "iam:UpdateUser",
      "iam:DeleteUser",
      "iam:TagUser",
      "iam:CreateAccessKey",
      "iam:ListAccessKeys",
      "iam:UpdateAccessKey",
      "iam:DeleteAccessKey",
      "iam:ListGroupsForUser",
      "iam:PutUserPolicy",
      "iam:GetUserPolicy",
      "iam:DeleteUserPolicy",
    ]
    resources = ["arn:aws:iam::${var.aws_admin_account_id}:user/homelab/sa/*"]
  }

  statement {
    effect = "Allow"
    actions = [
      "ssm:PutParameter",
      "ssm:DeleteParameter",
      "ssm:GetParameter",
      "ssm:GetParameters",
      "ssm:AddTagsToResource",
      "ssm:ListTagsForResource",
    ]
    resources = ["arn:aws:ssm:*:${var.aws_admin_account_id}:parameter/homelab/cluster/*"]
  }

  statement {
    effect = "Allow"
    actions = [
      "ssm:DescribeParameters",
    ]
    resources = ["*"]
  }

  statement {
    effect = "Deny"
    actions = [
      "ssm:PutParameter",
      "ssm:DeleteParameter",
    ]
    resources = [aws_ssm_parameter.cloudflare_origin_ca_key.arn]
  }
}

################### parameters ###################

resource "aws_ssm_parameter" "cloudflare_origin_ca_key" {
  name        = "/homelab/shared/cloudflare/token/origin-ca"
  description = "https://developers.cloudflare.com/fundamentals/api/get-started/ca-keys/#viewchange-your-origin-ca-keys"
  type        = "SecureString"
  value       = var.cloudflare_origin_ca_key
}


resource "aws_iam_group" "cf_origin_ca_cert_issuer" {
  name = "cloudflare-origin-ca-cert-issuer"
  path = "/homelab/shared/sa/"
}
resource "aws_iam_group_policy" "read_cf_origin_ca" {
  name   = "read-cf-origin-ca"
  group  = aws_iam_group.cf_origin_ca_cert_issuer.name
  policy = data.aws_iam_policy_document.cloudflare_origin_ca_cert_generator.json
}
data "aws_iam_policy_document" "cloudflare_origin_ca_cert_generator" {
  statement {
    effect    = "Allow"
    actions   = ["ssm:GetParameter"]
    resources = [aws_ssm_parameter.cloudflare_origin_ca_key.arn]
  }
}
