# Langfuse LLM Observability - ECS Fargate + RDS PostgreSQL
# Conditional on var.enable_langfuse
# Reuses chatbot ALB with host-based routing to save cost

# =============================================================================
# RDS PostgreSQL for Langfuse
# =============================================================================

resource "random_password" "langfuse_db" {
  count   = var.enable_langfuse ? 1 : 0
  length  = 32
  special = false
}

resource "random_password" "langfuse_nextauth_secret" {
  count   = var.enable_langfuse ? 1 : 0
  length  = 64
  special = false
}

resource "random_password" "langfuse_salt" {
  count   = var.enable_langfuse ? 1 : 0
  length  = 32
  special = false
}

resource "aws_secretsmanager_secret" "langfuse" {
  count = var.enable_langfuse ? 1 : 0
  name  = "${var.project_name}-langfuse-secrets"
}

resource "aws_secretsmanager_secret_version" "langfuse" {
  count     = var.enable_langfuse ? 1 : 0
  secret_id = aws_secretsmanager_secret.langfuse[0].id
  secret_string = jsonencode({
    db_password      = random_password.langfuse_db[0].result
    nextauth_secret  = random_password.langfuse_nextauth_secret[0].result
    salt             = random_password.langfuse_salt[0].result
  })
}

resource "aws_db_subnet_group" "langfuse" {
  count      = var.enable_langfuse ? 1 : 0
  name       = "${var.project_name}-langfuse"
  subnet_ids = var.public_subnet_ids

  tags = {
    Name = "${var.project_name}-langfuse"
  }
}

resource "aws_security_group" "langfuse_rds" {
  count       = var.enable_langfuse ? 1 : 0
  name        = "${var.project_name}-langfuse-rds"
  description = "RDS security group for Langfuse PostgreSQL"
  vpc_id      = var.vpc_id

  ingress {
    description     = "PostgreSQL from Langfuse ECS"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.langfuse_ecs[0].id]
  }

  egress {
    description = "All outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-langfuse-rds"
  }
}

resource "aws_db_instance" "langfuse" {
  count = var.enable_langfuse ? 1 : 0

  identifier     = "${var.project_name}-langfuse"
  engine         = "postgres"
  engine_version = "16"
  instance_class = "db.t4g.micro"

  allocated_storage     = 20
  max_allocated_storage = 50
  storage_type          = "gp3"

  db_name  = "langfuse"
  username = "langfuse"
  password = random_password.langfuse_db[0].result

  db_subnet_group_name   = aws_db_subnet_group.langfuse[0].name
  vpc_security_group_ids = [aws_security_group.langfuse_rds[0].id]
  publicly_accessible    = false

  backup_retention_period = 7
  skip_final_snapshot     = true
  deletion_protection     = false

  tags = {
    Name = "${var.project_name}-langfuse"
  }
}

# =============================================================================
# ECR Repository for Langfuse
# =============================================================================

resource "aws_ecr_repository" "langfuse" {
  count                = var.enable_langfuse ? 1 : 0
  name                 = "${var.project_name}-langfuse"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "langfuse" {
  count      = var.enable_langfuse ? 1 : 0
  repository = aws_ecr_repository.langfuse[0].name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last 3 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 3
      }
      action = {
        type = "expire"
      }
    }]
  })
}

# =============================================================================
# Security Group for Langfuse ECS
# =============================================================================

resource "aws_security_group" "langfuse_ecs" {
  count       = var.enable_langfuse ? 1 : 0
  name        = "${var.project_name}-langfuse-ecs"
  description = "ECS tasks security group for Langfuse"
  vpc_id      = var.vpc_id

  ingress {
    description     = "Container port from ALB"
    from_port       = 3000
    to_port         = 3000
    protocol        = "tcp"
    security_groups = [aws_security_group.chatbot_alb[0].id]
  }

  egress {
    description = "All outbound (RDS, ECR, etc.)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-langfuse-ecs"
  }
}

# =============================================================================
# ALB Target Group + Listener Rule (host-based routing on chatbot ALB)
# =============================================================================

resource "aws_lb_target_group" "langfuse" {
  count       = var.enable_langfuse ? 1 : 0
  name        = "${var.project_name}-langfuse"
  port        = 3000
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    path                = "/api/public/health"
    protocol            = "HTTP"
    port                = "traffic-port"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
    matcher             = "200"
  }

  tags = {
    Name = "${var.project_name}-langfuse"
  }
}

resource "aws_lb_listener_rule" "langfuse" {
  count        = var.enable_langfuse ? 1 : 0
  listener_arn = aws_lb_listener.chatbot[0].arn
  priority     = 10

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.langfuse[0].arn
  }

  condition {
    host_header {
      values = [var.langfuse_host_header]
    }
  }
}

# =============================================================================
# ECS Task Definition
# =============================================================================

resource "aws_cloudwatch_log_group" "langfuse_ecs" {
  count             = var.enable_langfuse ? 1 : 0
  name              = "/aws/ecs/${var.project_name}-langfuse"
  retention_in_days = var.log_retention_days

  tags = {
    Name = "${var.project_name}-langfuse-ecs"
  }
}

resource "aws_ecs_task_definition" "langfuse" {
  count                    = var.enable_langfuse ? 1 : 0
  family                   = "${var.project_name}-langfuse"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.ecs_task_execution[0].arn
  task_role_arn            = aws_iam_role.ecs_task_execution[0].arn

  container_definitions = jsonencode([{
    name  = "langfuse"
    image = "${aws_ecr_repository.langfuse[0].repository_url}:latest"

    portMappings = [{
      containerPort = 3000
      protocol      = "tcp"
    }]

    environment = [
      { name = "DATABASE_URL", value = "postgresql://langfuse:${random_password.langfuse_db[0].result}@${aws_db_instance.langfuse[0].endpoint}/langfuse" },
      { name = "NEXTAUTH_SECRET", value = random_password.langfuse_nextauth_secret[0].result },
      { name = "SALT", value = random_password.langfuse_salt[0].result },
      { name = "NEXTAUTH_URL", value = "https://${var.langfuse_host_header}" },
      { name = "HOSTNAME", value = "0.0.0.0" },
      { name = "PORT", value = "3000" },
      { name = "TELEMETRY_ENABLED", value = "false" },
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/aws/ecs/${var.project_name}-langfuse"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "langfuse"
      }
    }
  }])
}

# =============================================================================
# ECS Service
# =============================================================================

resource "aws_ecs_service" "langfuse" {
  count           = var.enable_langfuse ? 1 : 0
  name            = "${var.project_name}-langfuse"
  cluster         = aws_ecs_cluster.chatbot[0].id
  task_definition = aws_ecs_task_definition.langfuse[0].arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.public_subnet_ids
    security_groups  = [aws_security_group.langfuse_ecs[0].id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.langfuse[0].arn
    container_name   = "langfuse"
    container_port   = 3000
  }

  lifecycle {
    ignore_changes = [task_definition]
  }
}
