variable "project" {
  type    = string
  default = "booking"
}

variable "environment" {
  type    = string
  default = "test"
}

variable "region" {
  type    = string
  default = "ap-southeast-1"
}

variable "vpc_cidr" {
  type    = string
  default = "10.40.0.0/16"
}

variable "image_tag" {
  description = "Tag of the images used when a service is first created; pipelines deploy later versions"
  type        = string
  default     = "bootstrap"
}

variable "db_instance_class" {
  type    = string
  default = "db.t4g.medium"
}

variable "redis_node_type" {
  type    = string
  default = "cache.t4g.micro"
}

variable "github_repository" {
  description = "owner/repo allowed to deploy through GitHub Actions OIDC"
  type        = string
}

variable "service_scaling" {
  description = "Per-service task limits"
  type = map(object({
    min = number
    max = number
  }))
  default = {
    merchant     = { min = 2, max = 4 }
    catalogue    = { min = 2, max = 4 }
    availability = { min = 2, max = 10 }
    booking      = { min = 2, max = 8 }
    notification = { min = 2, max = 8 }
  }
}

variable "alarm_email" {
  description = "Optional e-mail subscribed to operational alarms"
  type        = string
  default     = ""
}
