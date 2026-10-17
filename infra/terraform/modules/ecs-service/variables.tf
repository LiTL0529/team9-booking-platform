variable "name" {
  description = "Service name, e.g. booking"
  type        = string
}

variable "environment" {
  type = string
}

variable "region" {
  type = string
}

variable "cluster_arn" {
  type = string
}

variable "cluster_name" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "vpc_cidr" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "service_connect_namespace_arn" {
  type = string
}

variable "image" {
  description = "Initial container image; later revisions are registered by the service's pipeline"
  type        = string
}

variable "cpu" {
  description = "Task CPU units; 256 = 0.25 vCPU so a single task saturates within the test budget"
  type        = number
  default     = 256
}

variable "memory" {
  type    = number
  default = 512
}

variable "min_tasks" {
  type    = number
  default = 2
}

variable "max_tasks" {
  type    = number
  default = 8
}

variable "cpu_target_percent" {
  type    = number
  default = 60
}

variable "environment_variables" {
  type    = map(string)
  default = {}
}

variable "secrets" {
  description = "Environment variable name => Secrets Manager ARN (optionally with :json-key::)"
  type        = map(string)
  default     = {}
}

variable "task_policy_json" {
  description = "Least-privilege IAM policy for the task role"
  type        = string
}

variable "nlb_arn" {
  description = "Internal NLB behind the API Gateway VPC link; null for services without a public API"
  type        = string
  default     = null
}

variable "nlb_listener_port" {
  type    = number
  default = null
}

variable "queue_name" {
  description = "When set, the service also scales on SQS backlog per task"
  type        = string
  default     = null
}

variable "backlog_per_task_target" {
  type    = number
  default = 200
}

variable "log_retention_days" {
  type    = number
  default = 14
}

variable "allowed_security_group_ids" {
  description = "Security groups (other services) allowed to call this service directly"
  type        = list(string)
  default     = []
}
