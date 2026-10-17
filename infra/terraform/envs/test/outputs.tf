output "web_url" {
  value = "https://${aws_cloudfront_distribution.web.domain_name}"
}

output "api_url" {
  description = "Direct API Gateway stage URL (the web app uses <web_url>/v1 instead)"
  value       = aws_api_gateway_stage.main.invoke_url
}

output "api_key_ids" {
  description = "Read values with: aws apigateway get-api-key --include-value --api-key <id>"
  value       = { for k, v in aws_api_gateway_api_key.client : k => v.id }
}

output "cognito_user_pool_id" {
  value = aws_cognito_user_pool.main.id
}

output "cognito_client_ids" {
  value = { for k, v in aws_cognito_user_pool_client.clients : k => v.id }
}

output "ecs_cluster" {
  value = aws_ecs_cluster.main.name
}

output "ecr_repositories" {
  value = { for k, v in aws_ecr_repository.service : k => v.repository_url }
}

output "private_subnet_ids" {
  value = aws_subnet.private[*].id
}

output "db_bootstrap_security_group" {
  value = aws_security_group.bootstrap.id
}

output "web_bucket" {
  value = aws_s3_bucket.web.bucket
}

output "cloudfront_distribution_id" {
  value = aws_cloudfront_distribution.web.id
}

output "deploy_role_arn" {
  value = aws_iam_role.deploy.arn
}

output "booking_topic_arn" {
  value = aws_sns_topic.events["booking-events"].arn
}

output "notification_queue_url" {
  value = aws_sqs_queue.events["notification-events"].url
}

output "dashboard_url" {
  value = "https://${var.region}.console.aws.amazon.com/cloudwatch/home?region=${var.region}#dashboards:name=${aws_cloudwatch_dashboard.main.dashboard_name}"
}
