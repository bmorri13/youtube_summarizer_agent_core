# Langfuse v3 LLM Observability — EC2 Docker Compose
# Conditional on var.enable_langfuse
# Reuses chatbot ALB with host-based routing to save cost
#
# Services: langfuse-web, langfuse-worker, PostgreSQL, Redis, ClickHouse, MinIO
# All running on a single EC2 instance via Docker Compose.

# =============================================================================
# Random Passwords / Secrets
# =============================================================================

resource "random_password" "langfuse_db" {
  count   = var.enable_langfuse ? 1 : 0
  length  = 32
  special = false
}

resource "random_password" "langfuse_nextauth" {
  count   = var.enable_langfuse ? 1 : 0
  length  = 64
  special = false
}

resource "random_password" "langfuse_encryption" {
  count   = var.enable_langfuse ? 1 : 0
  length  = 64
  special = false
}

resource "random_password" "langfuse_salt" {
  count   = var.enable_langfuse ? 1 : 0
  length  = 32
  special = false
}

resource "random_password" "langfuse_redis" {
  count   = var.enable_langfuse ? 1 : 0
  length  = 32
  special = false
}

resource "random_password" "langfuse_clickhouse" {
  count   = var.enable_langfuse ? 1 : 0
  length  = 32
  special = false
}

resource "random_password" "langfuse_minio" {
  count   = var.enable_langfuse ? 1 : 0
  length  = 32
  special = false
}

resource "random_password" "langfuse_init_public_key" {
  count   = var.enable_langfuse ? 1 : 0
  length  = 32
  special = false
}

resource "random_password" "langfuse_init_secret_key" {
  count   = var.enable_langfuse ? 1 : 0
  length  = 32
  special = false
}

locals {
  langfuse_public_key = var.enable_langfuse ? "lf_pk_${random_password.langfuse_init_public_key[0].result}" : ""
  langfuse_secret_key = var.enable_langfuse ? "lf_sk_${random_password.langfuse_init_secret_key[0].result}" : ""
}

# =============================================================================
# AMI — Amazon Linux 2023 (SSM agent pre-installed)
# =============================================================================

data "aws_ami" "amazon_linux_2023" {
  count       = var.enable_langfuse ? 1 : 0
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# =============================================================================
# Security Group
# =============================================================================

resource "aws_security_group" "langfuse_ec2" {
  count       = var.enable_langfuse ? 1 : 0
  name        = "${var.project_name}-langfuse-ec2"
  description = "Langfuse EC2 - port 3000 from ALB"
  vpc_id      = var.vpc_id

  ingress {
    description     = "Langfuse web from ALB"
    from_port       = 3000
    to_port         = 3000
    protocol        = "tcp"
    security_groups = [aws_security_group.chatbot_alb[0].id]
  }

  egress {
    description = "All outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-langfuse-ec2"
  }
}

# =============================================================================
# IAM — EC2 Instance Role (SSM Session Manager, no SSH needed)
# =============================================================================

resource "aws_iam_role" "langfuse_ec2" {
  count = var.enable_langfuse ? 1 : 0
  name  = "${var.project_name}-langfuse-ec2"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "langfuse_ssm" {
  count      = var.enable_langfuse ? 1 : 0
  role       = aws_iam_role.langfuse_ec2[0].name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "langfuse_ec2" {
  count = var.enable_langfuse ? 1 : 0
  name  = "${var.project_name}-langfuse-ec2"
  role  = aws_iam_role.langfuse_ec2[0].name
}

# =============================================================================
# EC2 Instance
# =============================================================================

# nosemgrep: terraform.aws.security.aws-ec2-has-public-ip.aws-ec2-has-public-ip
# Public IP required: instance is in a public subnet (no NAT Gateway) and needs
# internet access to pull Docker images. Ingress is restricted to port 3000 from ALB only.
resource "aws_instance" "langfuse" {
  count = var.enable_langfuse ? 1 : 0

  ami                    = data.aws_ami.amazon_linux_2023[0].id
  instance_type          = var.langfuse_instance_type
  subnet_id              = var.public_subnet_ids[0]
  vpc_security_group_ids = [aws_security_group.langfuse_ec2[0].id]
  iam_instance_profile   = aws_iam_instance_profile.langfuse_ec2[0].name

  associate_public_ip_address = true

  root_block_device {
    volume_size = 30
    volume_type = "gp3"
    encrypted   = true
  }

  user_data = templatefile("${path.module}/templates/langfuse-userdata.sh.tpl", {
    compose_file = templatefile("${path.module}/templates/langfuse-compose.yml.tpl", {
      db_password        = random_password.langfuse_db[0].result
      nextauth_secret    = random_password.langfuse_nextauth[0].result
      encryption_key     = random_password.langfuse_encryption[0].result
      salt               = random_password.langfuse_salt[0].result
      redis_password     = random_password.langfuse_redis[0].result
      clickhouse_password = random_password.langfuse_clickhouse[0].result
      minio_password     = random_password.langfuse_minio[0].result
      nextauth_url       = "https://${var.langfuse_host_header}"
      init_org_id        = "${var.project_name}-org"
      init_project_id    = var.project_name
      init_public_key    = local.langfuse_public_key
      init_secret_key    = local.langfuse_secret_key
      init_user_email    = var.langfuse_admin_email
      init_user_password = var.langfuse_admin_password
    })
  })

  tags = {
    Name = "${var.project_name}-langfuse"
  }

  lifecycle {
    ignore_changes = [ami, user_data]
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
  target_type = "instance"

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

resource "aws_lb_target_group_attachment" "langfuse" {
  count            = var.enable_langfuse ? 1 : 0
  target_group_arn = aws_lb_target_group.langfuse[0].arn
  target_id        = aws_instance.langfuse[0].id
  port             = 3000
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
