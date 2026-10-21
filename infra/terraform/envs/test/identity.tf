# Amazon Cognito: users, role groups and the custom:merchant_id attribute that the services read
# from ID tokens. One app client per client application (web, partner).

resource "aws_cognito_user_pool" "main" {
  name = local.name

  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  # Relaxed at the team's request so every demo account can use a short shared password.
  # Weak by design for the test environment; restore 8+ characters with mixed case before real use.
  password_policy {
    minimum_length    = 6
    require_lowercase = false
    require_uppercase = false
    require_numbers   = false
    require_symbols   = false
  }

  schema {
    name                     = "merchant_id"
    attribute_data_type      = "String"
    mutable                  = true
    developer_only_attribute = false
    string_attribute_constraints {
      min_length = 0
      max_length = 64
    }
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "admin_only"
      priority = 1
    }
  }
}

resource "aws_cognito_user_group" "roles" {
  for_each     = toset(["platform_admin", "merchant_admin", "merchant_staff", "customer"])
  name         = each.key
  user_pool_id = aws_cognito_user_pool.main.id
}

resource "aws_cognito_user_pool_client" "clients" {
  for_each                      = toset(["web", "partner"])
  name                          = "${local.name}-${each.key}"
  user_pool_id                  = aws_cognito_user_pool.main.id
  generate_secret               = false
  explicit_auth_flows           = ["ALLOW_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]
  prevent_user_existence_errors = "ENABLED"
  id_token_validity             = 60
  access_token_validity         = 60
  refresh_token_validity        = 1
  token_validity_units {
    id_token      = "minutes"
    access_token  = "minutes"
    refresh_token = "days"
  }
  # merchant_id is written only by the Merchant Service, never by users themselves
  read_attributes  = ["email", "custom:merchant_id"]
  write_attributes = ["email"]
}

locals {
  jwt_issuer   = "https://cognito-idp.${var.region}.amazonaws.com/${aws_cognito_user_pool.main.id}"
  jwt_audience = join(",", [for c in aws_cognito_user_pool_client.clients : c.id])
}
