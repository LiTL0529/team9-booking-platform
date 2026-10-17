# Shared module: one microservice = one ECS service + task definition on Fargate, with its own
# log group, least-privilege IAM roles, security group, NLB target group and auto scaling policy.

locals {
  full_name = "${var.environment}-${var.name}"
  container_env = [for k, v in merge(var.environment_variables, {
    SERVICE_NAME                = "${var.name}-service"
    ENVIRONMENT                 = var.environment
    AWS_REGION                  = var.region
    OTEL_ENABLED                = "true"
    OTEL_EXPORTER_OTLP_ENDPOINT = "http://127.0.0.1:4318"
    OTEL_ID_GENERATOR           = "xray"
  }) : { name = k, value = v }]
  container_secrets = [for k, v in var.secrets : { name = k, valueFrom = v }]
}

resource "aws_cloudwatch_log_group" "this" {
  name              = "/ecs/${local.full_name}"
  retention_in_days = var.log_retention_days
}

# --- IAM -------------------------------------------------------------------------------------

data "aws_iam_policy_document" "assume_ecs" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "${local.full_name}-execution"
  assume_role_policy = data.aws_iam_policy_document.assume_ecs.json
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "read_secrets" {
  count = length(var.secrets) > 0 ? 1 : 0
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = distinct([for v in values(var.secrets) : regex("^arn:aws:secretsmanager:[^:]+:[^:]+:secret:[^:]+", v)])
  }
}

resource "aws_iam_role_policy" "execution_secrets" {
  count  = length(var.secrets) > 0 ? 1 : 0
  name   = "read-own-secrets"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.read_secrets[0].json
}

resource "aws_iam_role" "task" {
  name               = "${local.full_name}-task"
  assume_role_policy = data.aws_iam_policy_document.assume_ecs.json
}

resource "aws_iam_role_policy" "task" {
  name   = "service"
  role   = aws_iam_role.task.id
  policy = var.task_policy_json
}

resource "aws_iam_role_policy_attachment" "xray" {
  role       = aws_iam_role.task.name
  policy_arn = "arn:aws:iam::aws:policy/AWSXRayDaemonWriteAccess"
}

# --- Network -----------------------------------------------------------------------------------

resource "aws_security_group" "this" {
  name        = local.full_name
  description = "${var.name} service tasks"
  vpc_id      = var.vpc_id

  # NLB health checks and forwarded traffic come from inside the VPC
  ingress {
    description = "API traffic via the internal NLB"
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  egress {
    description = "AWS APIs, database, cache and other services"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_lb_target_group" "this" {
  count       = var.attach_to_nlb ? 1 : 0
  name        = substr(local.full_name, 0, 32)
  port        = 8000
  protocol    = "TCP"
  target_type = "ip"
  vpc_id      = var.vpc_id

  deregistration_delay = 15

  # Liveness only (async, no database): a saturated-but-working task must not be killed by its
  # load balancer, which would push its load onto the remaining tasks (found in the first load test).
  health_check {
    protocol            = "HTTP"
    path                = "/health/live"
    interval            = 10
    timeout             = 6
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

resource "aws_lb_listener" "this" {
  count             = var.attach_to_nlb ? 1 : 0
  load_balancer_arn = var.nlb_arn
  port              = var.nlb_listener_port
  protocol          = "TCP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.this[0].arn
  }
}

# --- Task definition and service -------------------------------------------------------------

resource "aws_ecs_task_definition" "this" {
  family                   = local.full_name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.cpu
  memory                   = var.memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([
    {
      name         = "app"
      image        = var.image
      essential    = true
      portMappings = [{ name = "http", containerPort = 8000, protocol = "tcp" }]
      environment  = local.container_env
      secrets      = local.container_secrets
      healthCheck = {
        command     = ["CMD-SHELL", "python -c \"import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health/live',timeout=2)\""]
        interval    = 10
        timeout     = 3
        retries     = 3
        startPeriod = 20
      }
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.this.name
          awslogs-region        = var.region
          awslogs-stream-prefix = "app"
        }
      }
    },
    {
      # AWS Distro for OpenTelemetry: receives OTLP from the app and exports traces to X-Ray
      name      = "otel-collector"
      image     = "public.ecr.aws/aws-observability/aws-otel-collector:v0.41.1"
      essential = false
      command   = ["--config=/etc/ecs/ecs-default-config.yaml"]
      cpu       = 32
      memory    = 64
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.this.name
          awslogs-region        = var.region
          awslogs-stream-prefix = "otel"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "this" {
  name                   = var.name
  cluster                = var.cluster_arn
  task_definition        = aws_ecs_task_definition.this.arn
  desired_count          = var.min_tasks
  launch_type            = "FARGATE"
  enable_execute_command = false
  propagate_tags         = "SERVICE"

  health_check_grace_period_seconds  = 60
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  # A deployment whose tasks never become healthy is rolled back automatically.
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = concat([aws_security_group.this.id], var.allowed_security_group_ids)
    assign_public_ip = false
  }

  dynamic "load_balancer" {
    for_each = var.attach_to_nlb ? [1] : []
    content {
      target_group_arn = aws_lb_target_group.this[0].arn
      container_name   = "app"
      container_port   = 8000
    }
  }

  # Services find each other as http://<name>:8000 through ECS Service Connect.
  service_connect_configuration {
    enabled   = true
    namespace = var.service_connect_namespace_arn
    service {
      port_name      = "http"
      discovery_name = var.name
      client_alias {
        port     = 8000
        dns_name = var.name
      }
    }
  }

  lifecycle {
    # The pipeline registers new task definitions and auto scaling owns the task count.
    ignore_changes = [task_definition, desired_count]
  }

  depends_on = [aws_lb_listener.this]
}

# --- Auto scaling ----------------------------------------------------------------------------

resource "aws_appautoscaling_target" "this" {
  service_namespace  = "ecs"
  resource_id        = "service/${var.cluster_name}/${aws_ecs_service.this.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  min_capacity       = var.min_tasks
  max_capacity       = var.max_tasks
}

resource "aws_appautoscaling_policy" "cpu" {
  name               = "${local.full_name}-cpu"
  service_namespace  = aws_appautoscaling_target.this.service_namespace
  resource_id        = aws_appautoscaling_target.this.resource_id
  scalable_dimension = aws_appautoscaling_target.this.scalable_dimension
  policy_type        = "TargetTrackingScaling"

  target_tracking_scaling_policy_configuration {
    target_value       = var.cpu_target_percent
    scale_out_cooldown = 60
    scale_in_cooldown  = 180
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
  }
}

# Backlog per task = visible messages / running tasks (AWS-recommended SQS scaling metric).
resource "aws_appautoscaling_policy" "backlog" {
  count              = var.scale_on_queue ? 1 : 0
  name               = "${local.full_name}-sqs-backlog"
  service_namespace  = aws_appautoscaling_target.this.service_namespace
  resource_id        = aws_appautoscaling_target.this.resource_id
  scalable_dimension = aws_appautoscaling_target.this.scalable_dimension
  policy_type        = "TargetTrackingScaling"

  target_tracking_scaling_policy_configuration {
    target_value       = var.backlog_per_task_target
    scale_out_cooldown = 30
    scale_in_cooldown  = 120

    customized_metric_specification {
      metrics {
        id          = "visible"
        return_data = false
        metric_stat {
          stat = "Sum"
          metric {
            namespace   = "AWS/SQS"
            metric_name = "ApproximateNumberOfMessagesVisible"
            dimensions {
              name  = "QueueName"
              value = var.queue_name
            }
          }
        }
      }
      metrics {
        id          = "tasks"
        return_data = false
        metric_stat {
          stat = "Average"
          metric {
            namespace   = "ECS/ContainerInsights"
            metric_name = "RunningTaskCount"
            dimensions {
              name  = "ClusterName"
              value = var.cluster_name
            }
            dimensions {
              name  = "ServiceName"
              value = var.name
            }
          }
        }
      }
      metrics {
        id          = "backlog_per_task"
        expression  = "visible / IF(tasks > 0, tasks, 1)"
        label       = "Backlog per task"
        return_data = true
      }
    }
  }
}
