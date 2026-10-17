# GitHub Actions deploys through OpenID Connect: no long-lived AWS keys are stored in GitHub.

resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

locals {
  # GitHub's OIDC subject names the repository either as owner/repo or, for newer repositories,
  # with the immutable account and repository ids: owner@<owner id>/repo@<repo id>. Accept both,
  # spelled out exactly (no wildcards that would also match look-alike owner names).
  github_owner = split("/", var.github_repository)[0]
  github_repo  = split("/", var.github_repository)[1]
  github_subject_repos = compact([
    var.github_repository,
    var.github_repository_id == "" ? "" : "${local.github_owner}@${var.github_owner_id}/${local.github_repo}@${var.github_repository_id}",
  ])
}

resource "aws_iam_role" "deploy" {
  name = "${local.name}-github-deploy"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRoleWithWebIdentity"
      Principal = { Federated = aws_iam_openid_connect_provider.github.arn }
      Condition = {
        StringEquals = { "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com" }
        # Only workflows on main (or the protected "test" environment) of this repository
        StringLike = {
          "token.actions.githubusercontent.com:sub" = flatten([
            for repo in local.github_subject_repos : [
              "repo:${repo}:ref:refs/heads/main",
              "repo:${repo}:environment:test",
            ]
          ])
        }
      }
    }]
  })
}

data "aws_iam_policy_document" "deploy" {
  statement {
    sid       = "EcrLogin"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }
  statement {
    sid = "PushImages"
    actions = [
      "ecr:BatchCheckLayerAvailability", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload", "ecr:PutImage", "ecr:BatchGetImage", "ecr:DescribeImages",
      "ecr:DescribeImageScanFindings",
    ]
    resources = [for r in aws_ecr_repository.service : r.arn]
  }
  statement {
    sid       = "DeployServices"
    actions   = ["ecs:DescribeTaskDefinition", "ecs:RegisterTaskDefinition", "ecs:DescribeServices", "ecs:UpdateService", "ecs:ListTasks", "ecs:DescribeTasks"]
    resources = ["*"]
  }
  statement {
    sid       = "PassTaskRoles"
    actions   = ["iam:PassRole"]
    resources = flatten([for m in module.service : [m.task_role_arn, m.execution_role_arn]])
  }
  statement {
    sid       = "PublishWeb"
    actions   = ["s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
    resources = [aws_s3_bucket.web.arn, "${aws_s3_bucket.web.arn}/*"]
  }
  statement {
    sid       = "InvalidateCdn"
    actions   = ["cloudfront:CreateInvalidation"]
    resources = [aws_cloudfront_distribution.web.arn]
  }
  statement {
    sid       = "ReadApiKeysForSmokeTests"
    actions   = ["apigateway:GET"]
    resources = ["arn:aws:apigateway:${var.region}::/apikeys/*"]
  }
}

resource "aws_iam_role_policy" "deploy" {
  role   = aws_iam_role.deploy.id
  policy = data.aws_iam_policy_document.deploy.json
}
