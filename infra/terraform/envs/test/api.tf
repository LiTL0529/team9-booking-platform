# Amazon API Gateway (REST): routing per service, Cognito token checks, API keys with one usage
# plan per client application, throttling, and a private VPC link to the internal NLB.

locals {
  # route prefix => backend service and the HTTP methods that need no user token
  routes = {
    merchants     = { service = "merchant", public = [] }
    resources     = { service = "catalogue", public = ["GET"] }
    slots         = { service = "catalogue", public = ["ANY"] }
    availability  = { service = "availability", public = ["ANY"] }
    bookings      = { service = "booking", public = [] }
    notifications = { service = "notification", public = [] }
  }

  methods = merge([
    for route, cfg in local.routes : merge([
      for level in ["base", "proxy"] : {
        for m in distinct(concat(["ANY"], [for p in cfg.public : p if p != "ANY"])) :
        "${route}:${level}:${m}" => {
          route       = route
          level       = level
          http_method = m
          public      = contains(cfg.public, "ANY") || contains(cfg.public, m)
          port        = local.services[cfg.service].port
        }
      }
    ]...)
  ]...)

  usage_plans = {
    web      = { rate = 500, burst = 1000, quota = null }
    partner  = { rate = 10, burst = 20, quota = 50000 }
    loadtest = { rate = 1000, burst = 2000, quota = null }
  }
}

resource "aws_api_gateway_vpc_link" "nlb" {
  name        = local.name
  target_arns = [aws_lb.internal.arn]
}

resource "aws_api_gateway_rest_api" "main" {
  name           = local.name
  description    = "Multi Merchant Appointment Booking Platform public API"
  api_key_source = "HEADER"
  endpoint_configuration {
    types = ["REGIONAL"]
  }
}

resource "aws_api_gateway_authorizer" "cognito" {
  name            = "cognito"
  rest_api_id     = aws_api_gateway_rest_api.main.id
  type            = "COGNITO_USER_POOLS"
  provider_arns   = [aws_cognito_user_pool.main.arn]
  identity_source = "method.request.header.Authorization"
}

resource "aws_api_gateway_resource" "v1" {
  rest_api_id = aws_api_gateway_rest_api.main.id
  parent_id   = aws_api_gateway_rest_api.main.root_resource_id
  path_part   = "v1"
}

resource "aws_api_gateway_resource" "route" {
  for_each    = local.routes
  rest_api_id = aws_api_gateway_rest_api.main.id
  parent_id   = aws_api_gateway_resource.v1.id
  path_part   = each.key
}

resource "aws_api_gateway_resource" "proxy" {
  for_each    = local.routes
  rest_api_id = aws_api_gateway_rest_api.main.id
  parent_id   = aws_api_gateway_resource.route[each.key].id
  path_part   = "{proxy+}"
}

resource "aws_api_gateway_method" "route" {
  for_each           = local.methods
  rest_api_id        = aws_api_gateway_rest_api.main.id
  resource_id        = each.value.level == "base" ? aws_api_gateway_resource.route[each.value.route].id : aws_api_gateway_resource.proxy[each.value.route].id
  http_method        = each.value.http_method
  authorization      = each.value.public ? "NONE" : "COGNITO_USER_POOLS"
  authorizer_id      = each.value.public ? null : aws_api_gateway_authorizer.cognito.id
  api_key_required   = true
  request_parameters = each.value.level == "proxy" ? { "method.request.path.proxy" = true } : {}
}

resource "aws_api_gateway_integration" "route" {
  for_each                = local.methods
  rest_api_id             = aws_api_gateway_rest_api.main.id
  resource_id             = aws_api_gateway_method.route[each.key].resource_id
  http_method             = aws_api_gateway_method.route[each.key].http_method
  type                    = "HTTP_PROXY"
  integration_http_method = "ANY"
  connection_type         = "VPC_LINK"
  connection_id           = aws_api_gateway_vpc_link.nlb.id
  timeout_milliseconds    = 10000
  uri = each.value.level == "base" ? (
    "http://${aws_lb.internal.dns_name}:${each.value.port}/v1/${each.value.route}"
    ) : (
    "http://${aws_lb.internal.dns_name}:${each.value.port}/v1/${each.value.route}/{proxy}"
  )
  request_parameters = each.value.level == "proxy" ? { "integration.request.path.proxy" = "method.request.path.proxy" } : {}
}

resource "aws_api_gateway_deployment" "main" {
  rest_api_id = aws_api_gateway_rest_api.main.id
  triggers = {
    redeployment = sha1(jsonencode([local.methods, aws_api_gateway_integration.route, aws_api_gateway_integration.openapi]))
  }
  lifecycle {
    create_before_destroy = true
  }
}

# Versioned, read-only specifications use the same gateway and usage-plan key as
# the business API. No authentication or authorization rule on business routes changes.
resource "aws_api_gateway_resource" "docs" {
  rest_api_id = aws_api_gateway_rest_api.main.id
  parent_id   = aws_api_gateway_resource.v1.id
  path_part   = "docs"
}

resource "aws_api_gateway_resource" "docs_service" {
  for_each    = local.services
  rest_api_id = aws_api_gateway_rest_api.main.id
  parent_id   = aws_api_gateway_resource.docs.id
  path_part   = each.key
}

resource "aws_api_gateway_resource" "openapi" {
  for_each    = local.services
  rest_api_id = aws_api_gateway_rest_api.main.id
  parent_id   = aws_api_gateway_resource.docs_service[each.key].id
  path_part   = "openapi.json"
}

resource "aws_api_gateway_method" "openapi" {
  for_each         = local.services
  rest_api_id      = aws_api_gateway_rest_api.main.id
  resource_id      = aws_api_gateway_resource.openapi[each.key].id
  http_method      = "GET"
  authorization    = "NONE"
  api_key_required = true
}

resource "aws_api_gateway_integration" "openapi" {
  for_each                = local.services
  rest_api_id             = aws_api_gateway_rest_api.main.id
  resource_id             = aws_api_gateway_method.openapi[each.key].resource_id
  http_method             = aws_api_gateway_method.openapi[each.key].http_method
  type                    = "HTTP_PROXY"
  integration_http_method = "GET"
  connection_type         = "VPC_LINK"
  connection_id           = aws_api_gateway_vpc_link.nlb.id
  timeout_milliseconds    = 10000
  uri                     = "http://${aws_lb.internal.dns_name}:${each.value.port}/openapi.json"
}

resource "aws_cloudwatch_log_group" "api_access" {
  name              = "/apigateway/${local.name}"
  retention_in_days = 14
}

resource "aws_api_gateway_stage" "main" {
  rest_api_id          = aws_api_gateway_rest_api.main.id
  deployment_id        = aws_api_gateway_deployment.main.id
  stage_name           = var.environment
  xray_tracing_enabled = true
  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_access.arn
    format = jsonencode({
      requestId = "$context.requestId", ip = "$context.identity.sourceIp", method = "$context.httpMethod",
      path      = "$context.path", status = "$context.status", latency = "$context.responseLatency",
      apiKeyId  = "$context.identity.apiKeyId", user = "$context.authorizer.claims.sub"
    })
  }
}

resource "aws_api_gateway_method_settings" "all" {
  rest_api_id = aws_api_gateway_rest_api.main.id
  stage_name  = aws_api_gateway_stage.main.stage_name
  method_path = "*/*"
  settings {
    metrics_enabled        = true
    throttling_rate_limit  = 1500
    throttling_burst_limit = 3000
  }
}

resource "aws_api_gateway_usage_plan" "client" {
  for_each = local.usage_plans
  name     = "${local.name}-${each.key}"
  api_stages {
    api_id = aws_api_gateway_rest_api.main.id
    stage  = aws_api_gateway_stage.main.stage_name
  }
  throttle_settings {
    rate_limit  = each.value.rate
    burst_limit = each.value.burst
  }
  dynamic "quota_settings" {
    for_each = each.value.quota == null ? [] : [each.value.quota]
    content {
      limit  = quota_settings.value
      period = "DAY"
    }
  }
}

resource "aws_api_gateway_api_key" "client" {
  for_each = local.usage_plans
  name     = "${local.name}-${each.key}"
}

resource "aws_api_gateway_usage_plan_key" "client" {
  for_each      = local.usage_plans
  key_id        = aws_api_gateway_api_key.client[each.key].id
  key_type      = "API_KEY"
  usage_plan_id = aws_api_gateway_usage_plan.client[each.key].id
}
