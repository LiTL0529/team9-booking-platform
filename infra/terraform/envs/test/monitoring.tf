# CloudWatch dashboard and alarms. Traces go to X-Ray through the ADOT sidecar in each task.

resource "aws_iam_role" "apigw_logs" {
  name = "${local.name}-apigw-logs"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "apigateway.amazonaws.com" } }]
  })
}

resource "aws_iam_role_policy_attachment" "apigw_logs" {
  role       = aws_iam_role.apigw_logs.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonAPIGatewayPushToCloudWatchLogs"
}

resource "aws_api_gateway_account" "main" {
  cloudwatch_role_arn = aws_iam_role.apigw_logs.arn
}

resource "aws_sns_topic" "alarms" {
  name              = "${local.name}-alarms"
  kms_master_key_id = "alias/aws/sns"
}

resource "aws_sns_topic_subscription" "alarm_email" {
  count     = var.alarm_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

resource "aws_cloudwatch_metric_alarm" "dlq" {
  for_each            = aws_sqs_queue.dlq
  alarm_name          = "${each.value.name}-not-empty"
  alarm_description   = "Events that failed 5 times landed in the dead-letter queue"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = each.value.name }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "api_5xx" {
  alarm_name          = "${local.name}-api-5xx-rate"
  alarm_description   = "More than 1% of API requests failed with a server error"
  comparison_operator = "GreaterThanThreshold"
  threshold           = 1
  evaluation_periods  = 3
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]

  metric_query {
    id          = "rate"
    expression  = "100 * errors / IF(requests > 0, requests, 1)"
    label       = "5xx %"
    return_data = true
  }
  metric_query {
    id = "errors"
    metric {
      namespace   = "AWS/ApiGateway"
      metric_name = "5XXError"
      dimensions  = { ApiName = aws_api_gateway_rest_api.main.name, Stage = aws_api_gateway_stage.main.stage_name }
      stat        = "Sum"
      period      = 60
    }
  }
  metric_query {
    id = "requests"
    metric {
      namespace   = "AWS/ApiGateway"
      metric_name = "Count"
      dimensions  = { ApiName = aws_api_gateway_rest_api.main.name, Stage = aws_api_gateway_stage.main.stage_name }
      stat        = "Sum"
      period      = 60
    }
  }
}

locals {
  svc_names = keys(local.services)
}

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = local.name
  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric", x = 0, y = 0, width = 12, height = 6
        properties = {
          title   = "Running tasks per service (auto scaling)"
          region  = var.region
          stat    = "Average"
          period  = 60
          metrics = [for s in local.svc_names : ["ECS/ContainerInsights", "RunningTaskCount", "ClusterName", aws_ecs_cluster.main.name, "ServiceName", s]]
        }
      },
      {
        type = "metric", x = 12, y = 0, width = 12, height = 6
        properties = {
          title   = "CPU utilisation per service (%)"
          region  = var.region
          stat    = "Average"
          period  = 60
          metrics = [for s in local.svc_names : ["AWS/ECS", "CPUUtilization", "ClusterName", aws_ecs_cluster.main.name, "ServiceName", s]]
        }
      },
      {
        type = "metric", x = 0, y = 6, width = 12, height = 6
        properties = {
          title  = "API requests, latency and errors"
          region = var.region
          period = 60
          metrics = [
            ["AWS/ApiGateway", "Count", "ApiName", aws_api_gateway_rest_api.main.name, "Stage", var.environment, { stat = "Sum" }],
            [".", "Latency", ".", ".", ".", ".", { stat = "p95", yAxis = "right" }],
            [".", "5XXError", ".", ".", ".", ".", { stat = "Sum" }],
            [".", "4XXError", ".", ".", ".", ".", { stat = "Sum" }],
          ]
        }
      },
      {
        type = "metric", x = 12, y = 6, width = 12, height = 6
        properties = {
          title   = "Queue depth (event backlog)"
          region  = var.region
          stat    = "Maximum"
          period  = 60
          metrics = [for q in aws_sqs_queue.events : ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", q.name]]
        }
      },
      {
        type = "metric", x = 0, y = 12, width = 12, height = 6
        properties = {
          title  = "Database (shared RDS instance)"
          region = var.region
          period = 60
          metrics = [
            ["AWS/RDS", "CPUUtilization", "DBInstanceIdentifier", aws_db_instance.main.identifier, { stat = "Average" }],
            [".", "DatabaseConnections", ".", ".", { stat = "Maximum", yAxis = "right" }],
          ]
        }
      },
      {
        type = "metric", x = 12, y = 12, width = 12, height = 6
        properties = {
          title  = "Availability cache"
          region = var.region
          period = 60
          metrics = [
            ["AWS/ElastiCache", "CacheHits", "ReplicationGroupId", aws_elasticache_replication_group.main.id, { stat = "Sum" }],
            [".", "CacheMisses", ".", ".", { stat = "Sum" }],
          ]
        }
      },
    ]
  })
}
