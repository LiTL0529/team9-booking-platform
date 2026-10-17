# Test environment of the Multi Merchant Appointment Booking Platform on AWS.
#
#   cd infra/terraform/envs/test
#   terraform init -backend-config=backend.hcl
#   terraform apply -var-file=test.tfvars
#
# Files: network.tf, data.tf, messaging.tf, identity.tf, compute.tf, api.tf, web.tf,
#        monitoring.tf, cicd.tf

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.80"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
  backend "s3" {}
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project     = "booking-platform"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

data "aws_caller_identity" "current" {}
data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  name       = "${var.project}-${var.environment}"
  account_id = data.aws_caller_identity.current.account_id
  azs        = slice(data.aws_availability_zones.available.names, 0, 2)

  # One entry per microservice. port = listener port on the internal NLB.
  services = {
    merchant = {
      port      = 8081
      publishes = "merchant-events"
      consumes  = null
    }
    catalogue = {
      port      = 8082
      publishes = "catalogue-events"
      consumes  = null
    }
    availability = {
      port      = 8083
      publishes = null
      consumes  = "availability-events"
    }
    booking = {
      port      = 8084
      publishes = "booking-events"
      consumes  = "booking-slot-events"
    }
    notification = {
      port      = 8085
      publishes = null
      consumes  = "notification-events"
    }
  }
}
