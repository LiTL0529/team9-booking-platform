# Container registry, ECS cluster, internal NLB (target of the API Gateway VPC link) and the five
# microservices, each created from the shared ecs-service module.

resource "aws_ecr_repository" "service" {
  for_each             = local.services
  name                 = "${var.project}/${each.key}"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = true
  image_scanning_configuration {
    scan_on_push = true
  }
  encryption_configuration {
    encryption_type = "AES256"
  }
}

resource "aws_ecr_lifecycle_policy" "service" {
  for_each   = aws_ecr_repository.service
  repository = each.value.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "keep the last 20 images"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 20 }
      action       = { type = "expire" }
    }]
  })
}

resource "aws_ecs_cluster" "main" {
  name = local.name
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_ecs_cluster_capacity_providers" "main" {
  cluster_name       = aws_ecs_cluster.main.name
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]
  default_capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
  }
}

resource "aws_service_discovery_http_namespace" "main" {
  name        = local.name
  description = "ECS Service Connect namespace"
}

resource "aws_lb" "internal" {
  name                             = "${local.name}-nlb"
  internal                         = true
  load_balancer_type               = "network"
  subnets                          = aws_subnet.private[*].id
  enable_cross_zone_load_balancing = true
}

# --- Least-privilege task policies ------------------------------------------------------------

data "aws_iam_policy_document" "task" {
  for_each = local.services

  dynamic "statement" {
    for_each = each.value.publishes == null ? [] : [each.value.publishes]
    content {
      sid       = "PublishOwnEvents"
      actions   = ["sns:Publish"]
      resources = [aws_sns_topic.events[statement.value].arn]
    }
  }

  dynamic "statement" {
    for_each = each.value.consumes == null ? [] : [each.value.consumes]
    content {
      sid = "ConsumeOwnQueue"
      actions = [
        "sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:DeleteMessageBatch",
        "sqs:ChangeMessageVisibility", "sqs:GetQueueAttributes",
      ]
      resources = [aws_sqs_queue.events[statement.value].arn]
    }
  }

  dynamic "statement" {
    for_each = each.key == "merchant" ? [1] : []
    content {
      sid = "WriteMerchantRolesToCognito"
      actions = [
        "cognito-idp:AdminUpdateUserAttributes",
        "cognito-idp:AdminAddUserToGroup",
        "cognito-idp:AdminRemoveUserFromGroup",
      ]
      resources = [aws_cognito_user_pool.main.arn]
    }
  }
}

locals {
  service_environment = {
    merchant = {
      IDENTITY_PROVIDER    = "cognito"
      COGNITO_USER_POOL_ID = aws_cognito_user_pool.main.id
    }
    catalogue    = {}
    availability = { CONSUMER_CONCURRENCY = "2", DB_POOL_SIZE = "10" }
    booking      = { CATALOGUE_URL = "http://catalogue:8000", DB_POOL_SIZE = "10" }
    notification = { CONSUMER_CONCURRENCY = "2" }
  }
}

module "service" {
  source   = "../../modules/ecs-service"
  for_each = local.services

  name                          = each.key
  environment                   = var.environment
  region                        = var.region
  cluster_arn                   = aws_ecs_cluster.main.arn
  cluster_name                  = aws_ecs_cluster.main.name
  vpc_id                        = aws_vpc.main.id
  vpc_cidr                      = var.vpc_cidr
  private_subnet_ids            = aws_subnet.private[*].id
  service_connect_namespace_arn = aws_service_discovery_http_namespace.main.arn
  image                         = "${aws_ecr_repository.service[each.key].repository_url}:${var.image_tag}"
  min_tasks                     = var.service_scaling[each.key].min
  max_tasks                     = var.service_scaling[each.key].max
  cpu_target_percent            = each.key == "availability" ? 35 : 50
  nlb_arn                       = aws_lb.internal.arn
  nlb_listener_port             = each.value.port
  attach_to_nlb                 = true
  scale_on_queue                = each.key == "notification"
  queue_name                    = each.key == "notification" ? aws_sqs_queue.events["notification-events"].name : null
  task_policy_json              = data.aws_iam_policy_document.task[each.key].json

  environment_variables = merge(
    {
      JWT_ISSUER   = local.jwt_issuer
      JWKS_URL     = "${local.jwt_issuer}/.well-known/jwks.json"
      JWT_AUDIENCE = local.jwt_audience
      DB_POOL_SIZE = "5"
    },
    each.value.publishes == null ? {} : { PUBLISH_TOPIC_ARN = aws_sns_topic.events[each.value.publishes].arn },
    each.value.consumes == null ? {} : { CONSUME_QUEUE_URL = aws_sqs_queue.events[each.value.consumes].url },
    each.key == "availability" ? {
      REDIS_URL = "rediss://${aws_elasticache_replication_group.main.primary_endpoint_address}:6379/0"
    } : {},
    local.service_environment[each.key],
  )

  secrets = {
    DATABASE_URL = aws_secretsmanager_secret.database_url[each.key].arn
  }
}

# --- One-off database bootstrap task -----------------------------------------------------------
# aws ecs run-task --cluster <cluster> --task-definition <env>-db-bootstrap --launch-type FARGATE \
#   --network-configuration 'awsvpcConfiguration={subnets=[...],securityGroups=[...]}'

resource "aws_security_group" "bootstrap" {
  name        = "${local.name}-db-bootstrap"
  description = "One-off database bootstrap task"
  vpc_id      = aws_vpc.main.id
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_iam_role" "bootstrap_execution" {
  name = "${local.name}-db-bootstrap-execution"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "ecs-tasks.amazonaws.com" } }]
  })
}

resource "aws_iam_role_policy_attachment" "bootstrap_execution" {
  role       = aws_iam_role.bootstrap_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "bootstrap_secrets" {
  role = aws_iam_role.bootstrap_execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "secretsmanager:GetSecretValue"
      Resource = [aws_secretsmanager_secret.db_bootstrap.arn, aws_db_instance.main.master_user_secret[0].secret_arn]
    }]
  })
}

resource "aws_cloudwatch_log_group" "bootstrap" {
  name              = "/ecs/${local.name}-db-bootstrap"
  retention_in_days = 7
}

resource "aws_ecs_task_definition" "db_bootstrap" {
  family                   = "${local.name}-db-bootstrap"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.bootstrap_execution.arn
  container_definitions = jsonencode([{
    name      = "bootstrap"
    image     = "${aws_ecr_repository.service["merchant"].repository_url}:${var.image_tag}"
    essential = true
    command   = ["python", "-m", "platform_common.db_bootstrap"]
    environment = [
      { name = "MASTER_DB_HOST", value = aws_db_instance.main.address },
      { name = "MASTER_DB_USER", value = aws_db_instance.main.username },
    ]
    secrets = [
      { name = "MASTER_DB_PASSWORD", valueFrom = "${aws_db_instance.main.master_user_secret[0].secret_arn}:password::" },
      { name = "DB_BOOTSTRAP_SPEC", valueFrom = aws_secretsmanager_secret.db_bootstrap.arn },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.bootstrap.name
        awslogs-region        = var.region
        awslogs-stream-prefix = "bootstrap"
      }
    }
  }])
}
