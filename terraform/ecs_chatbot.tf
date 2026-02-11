# ECS Fargate deployment for RAG Chatbot
# Conditional on enable_knowledge_base (chatbot requires KB)
# ALB provides HTTP; Cloudflare CNAME + proxy handles HTTPS externally

# =============================================================================
# ECR Repository
# =============================================================================

resource "aws_ecr_repository" "chatbot" {
  count                = var.enable_knowledge_base ? 1 : 0
  name                 = "${var.project_name}-chatbot"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "chatbot" {
  count      = var.enable_knowledge_base ? 1 : 0
  repository = aws_ecr_repository.chatbot[0].name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last 5 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 5
      }
      action = {
        type = "expire"
      }
    }]
  })
}

# =============================================================================
# Cloudflare IP Ranges (restrict ALB to Cloudflare-only traffic)
# =============================================================================

data "http" "cloudflare_ipv4" {
  url = "https://www.cloudflare.com/ips-v4/"
}

data "http" "cloudflare_ipv6" {
  url = "https://www.cloudflare.com/ips-v6/"
}

locals {
  cloudflare_ipv4_ranges = [for cidr in split("\n", trimspace(data.http.cloudflare_ipv4.response_body)) : cidr if cidr != ""]
  cloudflare_ipv6_ranges = [for cidr in split("\n", trimspace(data.http.cloudflare_ipv6.response_body)) : cidr if cidr != ""]
}

# =============================================================================
# Security Groups
# =============================================================================

resource "aws_security_group" "chatbot_alb" {
  count       = var.enable_knowledge_base ? 1 : 0
  name        = "${var.project_name}-chatbot-alb"
  description = "ALB security group for chatbot (Cloudflare only)"
  vpc_id      = var.vpc_id

  ingress {
    description = "HTTP from Cloudflare IPv4"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = local.cloudflare_ipv4_ranges
  }

  ingress {
    description      = "HTTP from Cloudflare IPv6"
    from_port        = 80
    to_port          = 80
    protocol         = "tcp"
    ipv6_cidr_blocks = local.cloudflare_ipv6_ranges
  }

  egress {
    description = "All outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-chatbot-alb"
  }
}

resource "aws_security_group" "chatbot_ecs" {
  count       = var.enable_knowledge_base ? 1 : 0
  name        = "${var.project_name}-chatbot-ecs"
  description = "ECS tasks security group for chatbot"
  vpc_id      = var.vpc_id

  ingress {
    description     = "Container port from ALB"
    from_port       = 8081
    to_port         = 8081
    protocol        = "tcp"
    security_groups = [aws_security_group.chatbot_alb[0].id]
  }

  egress {
    description = "All outbound (Bedrock API, ECR, etc.)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-chatbot-ecs"
  }
}

# =============================================================================
# Application Load Balancer
# =============================================================================

resource "aws_lb" "chatbot" {
  count              = var.enable_knowledge_base ? 1 : 0
  name               = "${var.project_name}-chatbot"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.chatbot_alb[0].id]
  subnets            = var.public_subnet_ids

  tags = {
    Name = "${var.project_name}-chatbot"
  }
}

resource "aws_lb_target_group" "chatbot" {
  count       = var.enable_knowledge_base ? 1 : 0
  name        = "${var.project_name}-chatbot"
  port        = 8081
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    path                = "/health"
    protocol            = "HTTP"
    port                = "traffic-port"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
    matcher             = "200"
  }

  tags = {
    Name = "${var.project_name}-chatbot"
  }
}

resource "aws_lb_listener" "chatbot" {
  count             = var.enable_knowledge_base ? 1 : 0
  load_balancer_arn = aws_lb.chatbot[0].arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.chatbot[0].arn
  }
}

# =============================================================================
# ECS Cluster
# =============================================================================

resource "aws_ecs_cluster" "chatbot" {
  count = var.enable_knowledge_base ? 1 : 0
  name  = "${var.project_name}-chatbot"

  tags = {
    Name = "${var.project_name}-chatbot"
  }
}

resource "aws_cloudwatch_log_group" "chatbot_ecs" {
  count             = var.enable_knowledge_base ? 1 : 0
  name              = "/aws/ecs/${var.project_name}-chatbot"
  retention_in_days = var.log_retention_days

  tags = {
    Name = "${var.project_name}-chatbot-ecs"
  }
}

# =============================================================================
# ECS Task Definition
# =============================================================================

resource "aws_ecs_task_definition" "chatbot" {
  count                    = var.enable_knowledge_base ? 1 : 0
  family                   = "${var.project_name}-chatbot"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.chatbot_fargate_cpu
  memory                   = var.chatbot_fargate_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution[0].arn
  task_role_arn            = aws_iam_role.ecs_task[0].arn

  container_definitions = jsonencode([{
    name  = "chatbot"
    image = "${aws_ecr_repository.chatbot[0].repository_url}:latest"

    portMappings = [{
      containerPort = 8081
      protocol      = "tcp"
    }]

    environment = concat(
      [
        { name = "KNOWLEDGE_BASE_ID", value = aws_bedrockagent_knowledge_base.notes[0].id },
        { name = "CHATBOT_MODEL_ID", value = var.chatbot_model_id },
        { name = "BEDROCK_GUARDRAIL_ID", value = aws_bedrock_guardrail.chatbot[0].guardrail_id },
        { name = "BEDROCK_GUARDRAIL_VERSION", value = aws_bedrock_guardrail_version.chatbot[0].version },
        { name = "KB_MAX_RESULTS", value = "5" },
        { name = "AWS_REGION", value = var.aws_region },
        { name = "LOG_LEVEL", value = "INFO" },
      ],
      var.enable_langfuse ? [
        { name = "LANGFUSE_HOST", value = "https://${var.langfuse_host_header}" },
        { name = "LANGFUSE_PUBLIC_KEY", value = local.langfuse_public_key },
        { name = "LANGFUSE_SECRET_KEY", value = local.langfuse_secret_key },
      ] : [],
      var.enable_observability ? [
        { name = "AGENT_OBSERVABILITY_ENABLED", value = "true" },
        { name = "OTEL_SERVICE_NAME", value = "${var.project_name}-chatbot" },
        { name = "OTEL_PYTHON_DISTRO", value = "aws_distro" },
        { name = "OTEL_PYTHON_CONFIGURATOR", value = "aws_configurator" },
        { name = "OTEL_EXPORTER_OTLP_PROTOCOL", value = "http/protobuf" },
        { name = "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", value = "https://xray.${var.aws_region}.amazonaws.com/v1/traces" },
        { name = "OTEL_TRACES_EXPORTER", value = "otlp" },
        { name = "OTEL_METRICS_EXPORTER", value = "none" },
        { name = "OTEL_LOGS_EXPORTER", value = "otlp" },
        { name = "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", value = "https://logs.${var.aws_region}.amazonaws.com/v1/logs" },
        { name = "OTEL_PYTHON_LOGGING_AUTO_INSTRUMENTATION_ENABLED", value = "true" },
        { name = "OTEL_RESOURCE_ATTRIBUTES", value = "service.name=${var.project_name}-chatbot,aws.log.group.names=/aws/bedrock-agentcore/runtimes/${var.project_name}-chatbot" },
        { name = "OTEL_EXPORTER_OTLP_LOGS_HEADERS", value = "x-aws-log-group=/aws/bedrock-agentcore/runtimes/${var.project_name}-chatbot,x-aws-log-stream=runtime-logs,x-aws-metric-namespace=bedrock-agentcore" },
        { name = "OTEL_SPAN_ATTRIBUTE_VALUE_LENGTH_LIMIT", value = "4096" },
        { name = "OTEL_SPAN_ATTRIBUTE_COUNT_LIMIT", value = "128" },
        { name = "OTEL_PYTHON_EXCLUDED_URLS", value = "health,^/$,^/assets" },
        { name = "OTEL_PYTHON_FASTAPI_EXCLUDED_URLS", value = "health,^/$,^/assets" },
      ] : []
    )

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/aws/ecs/${var.project_name}-chatbot"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "chatbot"
      }
    }
  }])
}

# =============================================================================
# ECS Service
# =============================================================================

resource "aws_ecs_service" "chatbot" {
  count           = var.enable_knowledge_base ? 1 : 0
  name            = "${var.project_name}-chatbot"
  cluster         = aws_ecs_cluster.chatbot[0].id
  task_definition = aws_ecs_task_definition.chatbot[0].arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.public_subnet_ids
    security_groups  = [aws_security_group.chatbot_ecs[0].id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.chatbot[0].arn
    container_name   = "chatbot"
    container_port   = 8081
  }

  lifecycle {
    ignore_changes = [task_definition]
  }
}

# =============================================================================
# IAM — Task Execution Role (pull images, push logs)
# =============================================================================

resource "aws_iam_role" "ecs_task_execution" {
  count = var.enable_knowledge_base ? 1 : 0
  name  = "${var.project_name}-ecs-task-execution"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution" {
  count      = var.enable_knowledge_base ? 1 : 0
  role       = aws_iam_role.ecs_task_execution[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# =============================================================================
# IAM — Task Role (runtime permissions for Bedrock)
# =============================================================================

resource "aws_iam_role" "ecs_task" {
  count = var.enable_knowledge_base ? 1 : 0
  name  = "${var.project_name}-ecs-task"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "ecs_task_bedrock" {
  count = var.enable_knowledge_base ? 1 : 0
  name  = "${var.project_name}-ecs-task-bedrock"
  role  = aws_iam_role.ecs_task[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["bedrock:Retrieve"]
        Resource = [aws_bedrockagent_knowledge_base.notes[0].arn]
      },
      {
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream"
        ]
        Resource = [
          "arn:aws:bedrock:*::foundation-model/anthropic.*",
          "arn:aws:bedrock:${var.aws_region}:${data.aws_caller_identity.current.account_id}:inference-profile/us.anthropic.*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "bedrock:ApplyGuardrail",
          "bedrock:GetGuardrail"
        ]
        Resource = [aws_bedrock_guardrail.chatbot[0].guardrail_arn]
      }
    ]
  })
}

resource "aws_iam_role_policy" "ecs_task_xray" {
  count = var.enable_knowledge_base && var.enable_observability ? 1 : 0
  name  = "${var.project_name}-ecs-task-xray"
  role  = aws_iam_role.ecs_task[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = [
        "xray:PutTraceSegments",
        "xray:PutTelemetryRecords",
        "xray:GetSamplingRules",
        "xray:GetSamplingTargets"
      ]
      Resource = "*"
    }]
  })
}

resource "aws_iam_role_policy" "ecs_task_agentcore_logs" {
  count = var.enable_knowledge_base && var.enable_observability ? 1 : 0
  name  = "${var.project_name}-ecs-task-agentcore-logs"
  role  = aws_iam_role.ecs_task[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "logs:CreateLogStream",
        "logs:PutLogEvents",
        "logs:DescribeLogGroups",
        "logs:DescribeLogStreams"
      ]
      Resource = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/bedrock-agentcore/runtimes/*:*"
    }]
  })
}

