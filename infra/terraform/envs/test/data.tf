# One RDS for PostgreSQL instance holding five databases (one per service, each with its own
# login), and ElastiCache Redis for the availability cache.

resource "aws_db_subnet_group" "main" {
  name       = local.name
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_security_group" "db" {
  name        = "${local.name}-db"
  description = "PostgreSQL reachable only from service tasks"
  vpc_id      = aws_vpc.main.id
}

resource "aws_vpc_security_group_ingress_rule" "db_from_services" {
  for_each                     = local.services
  security_group_id            = aws_security_group.db.id
  referenced_security_group_id = module.service[each.key].security_group_id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
  description                  = "${each.key} service"
}

resource "aws_vpc_security_group_ingress_rule" "db_from_bootstrap" {
  security_group_id            = aws_security_group.db.id
  referenced_security_group_id = aws_security_group.bootstrap.id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
  description                  = "one-off database bootstrap task"
}

resource "aws_db_parameter_group" "main" {
  name   = "${local.name}-pg16"
  family = "postgres16"
  parameter {
    name         = "rds.force_ssl"
    value        = "1"
    apply_method = "pending-reboot"
  }
  parameter {
    name  = "log_min_duration_statement"
    value = "500"
  }
}

resource "aws_db_instance" "main" {
  identifier                   = local.name
  engine                       = "postgres"
  engine_version               = "16" # current 16.x minor; minors are retired over time
  auto_minor_version_upgrade   = true
  instance_class               = var.db_instance_class
  allocated_storage            = 20
  max_allocated_storage        = 100
  storage_type                 = "gp3"
  storage_encrypted            = true
  db_subnet_group_name         = aws_db_subnet_group.main.name
  vpc_security_group_ids       = [aws_security_group.db.id]
  parameter_group_name         = aws_db_parameter_group.main.name
  username                     = "platform_admin"
  manage_master_user_password  = true # master password lives in Secrets Manager
  multi_az                     = false
  backup_retention_period      = 3
  performance_insights_enabled = true
  deletion_protection          = false
  skip_final_snapshot          = true
  apply_immediately            = true
}

# Per-service database credentials, generated here and stored in Secrets Manager.
resource "random_password" "db" {
  for_each = local.services
  length   = 32
  special  = false
}

resource "aws_secretsmanager_secret" "database_url" {
  for_each                = local.services
  name                    = "${local.name}/${each.key}/database-url"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "database_url" {
  for_each      = local.services
  secret_id     = aws_secretsmanager_secret.database_url[each.key].id
  secret_string = "postgresql+psycopg://${each.key}_svc:${random_password.db[each.key].result}@${aws_db_instance.main.address}:5432/${each.key}?sslmode=require"
}

resource "aws_secretsmanager_secret" "db_bootstrap" {
  name                    = "${local.name}/db-bootstrap-spec"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "db_bootstrap" {
  secret_id = aws_secretsmanager_secret.db_bootstrap.id
  secret_string = jsonencode([for name, _ in local.services : {
    database = name
    user     = "${name}_svc"
    password = random_password.db[name].result
  }])
}

# --- Redis --------------------------------------------------------------------------------------

resource "aws_elasticache_subnet_group" "main" {
  name       = local.name
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_security_group" "redis" {
  name        = "${local.name}-redis"
  description = "Redis reachable only from the Availability Service"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [module.service["availability"].security_group_id]
  }
}

resource "aws_elasticache_replication_group" "main" {
  replication_group_id       = local.name
  description                = "Availability search cache"
  engine                     = "redis"
  engine_version             = "7.1"
  node_type                  = var.redis_node_type
  num_cache_clusters         = 1
  port                       = 6379
  subnet_group_name          = aws_elasticache_subnet_group.main.name
  security_group_ids         = [aws_security_group.redis.id]
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  apply_immediately          = true
}
