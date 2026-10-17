# AWS CodeBuild builds the service images in the cloud, so no local Docker is needed.
# scripts/aws_build_images.py zips the repository, uploads it here and starts the build.

resource "aws_s3_bucket" "build_source" {
  bucket        = "${local.name}-build-source-${local.account_id}"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "build_source" {
  bucket                  = aws_s3_bucket.build_source.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "build_source" {
  bucket = aws_s3_bucket.build_source.id
  rule {
    id     = "expire-sources"
    status = "Enabled"
    filter {}
    expiration {
      days = 7
    }
  }
}

resource "aws_cloudwatch_log_group" "build" {
  name              = "/codebuild/${local.name}-images"
  retention_in_days = 7
}

resource "aws_iam_role" "build" {
  name = "${local.name}-codebuild"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "codebuild.amazonaws.com" } }]
  })
}

resource "aws_iam_role_policy" "build" {
  role = aws_iam_role.build.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.build.arn}:*" },
      { Effect = "Allow", Action = ["s3:GetObject", "s3:GetObjectVersion"], Resource = "${aws_s3_bucket.build_source.arn}/*" },
      { Effect = "Allow", Action = "ecr:GetAuthorizationToken", Resource = "*" },
      {
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload", "ecr:PutImage", "ecr:BatchGetImage", "ecr:DescribeImages",
        ]
        Resource = [for r in aws_ecr_repository.service : r.arn]
      },
    ]
  })
}

resource "aws_codebuild_project" "images" {
  name          = "${local.name}-images"
  description   = "Builds and pushes the five service images to ECR"
  service_role  = aws_iam_role.build.arn
  build_timeout = 30

  source {
    type      = "S3"
    location  = "${aws_s3_bucket.build_source.bucket}/source.zip"
    buildspec = <<-EOT
      version: 0.2
      phases:
        pre_build:
          commands:
            - aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $REGISTRY
        build:
          commands:
            - |
              for s in $SERVICES; do
                if aws ecr describe-images --repository-name booking/$s --image-ids imageTag=$IMAGE_TAG >/dev/null 2>&1; then
                  echo "booking/$s:$IMAGE_TAG already exists, skipping"; continue
                fi
                docker build -f docker/service.Dockerfile --build-arg SERVICE=$s --build-arg VERSION=$IMAGE_TAG \
                  -t $REGISTRY/booking/$s:$IMAGE_TAG . && docker push $REGISTRY/booking/$s:$IMAGE_TAG || exit 1
              done
    EOT
  }

  artifacts {
    type = "NO_ARTIFACTS"
  }

  environment {
    type            = "LINUX_CONTAINER"
    compute_type    = "BUILD_GENERAL1_MEDIUM"
    image           = "aws/codebuild/amazonlinux-x86_64-standard:5.0"
    privileged_mode = true # required to run docker build

    environment_variable {
      name  = "REGISTRY"
      value = "${local.account_id}.dkr.ecr.${var.region}.amazonaws.com"
    }
    environment_variable {
      name  = "SERVICES"
      value = "merchant catalogue availability booking notification"
    }
    environment_variable {
      name  = "IMAGE_TAG"
      value = var.image_tag
    }
  }

  logs_config {
    cloudwatch_logs {
      group_name = aws_cloudwatch_log_group.build.name
    }
  }
}

output "build_project" {
  value = aws_codebuild_project.images.name
}

output "build_source_bucket" {
  value = aws_s3_bucket.build_source.bucket
}
