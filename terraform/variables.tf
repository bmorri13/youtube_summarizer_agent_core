variable "aws_region" {
  description = "AWS region for deployment"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name (e.g., prod, staging, dev)"
  type        = string
  default     = "prod"
}

variable "project_name" {
  description = "Project name used for resource naming"
  type        = string
  default     = "youtube-analyzer"
}

variable "anthropic_api_key" {
  description = "Anthropic API key for Claude"
  type        = string
  sensitive   = true
}

variable "slack_webhook_url" {
  description = "Slack webhook URL for notifications"
  type        = string
  sensitive   = true
  default     = ""
}

variable "lambda_memory_size" {
  description = "Memory size for Lambda function in MB"
  type        = number
  default     = 1024
}

variable "lambda_timeout" {
  description = "Timeout for Lambda function in seconds"
  type        = number
  default     = 300
}

variable "claude_model" {
  description = "Claude model ID to use"
  type        = string
  default     = "claude-sonnet-4-20250514"
}

variable "monitor_channel_urls" {
  description = "Comma-separated YouTube channel URLs to monitor"
  type        = string
  default     = ""
}

variable "enable_observability" {
  description = "Enable OpenTelemetry tracing and CloudWatch custom logging"
  type        = bool
  default     = true
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days"
  type        = number
  default     = 30
}

variable "enable_alarms" {
  description = "Enable CloudWatch alarms"
  type        = bool
  default     = false
}

variable "alarm_email" {
  description = "Email address for alarm notifications"
  type        = string
  default     = ""
}

variable "enable_knowledge_base" {
  description = "Enable Bedrock Knowledge Base for semantic search over notes"
  type        = bool
  default     = true
}

variable "kb_embedding_model" {
  description = "Bedrock embedding model for vectorization"
  type        = string
  default     = "amazon.titan-embed-text-v2:0"
}

variable "chatbot_model_id" {
  description = "Bedrock model ID for the RAG chatbot"
  type        = string
  default     = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
}

variable "vpc_id" {
  description = "VPC ID for ECS Fargate chatbot deployment"
  type        = string
  default     = "vpc-00fa7c3abcd1a7236"
}

variable "public_subnet_ids" {
  description = "Public subnet IDs for ALB and ECS tasks"
  type        = list(string)
  default     = ["subnet-0c4148ebe5b5508d2", "subnet-02d4d1fa1b3d8ab0c"]
}

variable "chatbot_fargate_cpu" {
  description = "CPU units for Fargate chatbot task (1024 = 1 vCPU)"
  type        = number
  default     = 1024
}

variable "chatbot_fargate_memory" {
  description = "Memory in MB for Fargate chatbot task"
  type        = number
  default     = 2048
}

variable "enable_langfuse" {
  description = "Enable Langfuse v3 LLM observability (EC2 Docker Compose)"
  type        = bool
  default     = false
}

variable "langfuse_host_header" {
  description = "Host header for ALB routing to Langfuse (e.g., langfuse.yourdomain.com)"
  type        = string
  default     = "langfuse.localhost"
}

variable "langfuse_instance_type" {
  description = "EC2 instance type for Langfuse (needs 4GB+ RAM)"
  type        = string
  default     = "t3.medium"
}

variable "langfuse_admin_email" {
  description = "Admin user email for Langfuse web UI"
  type        = string
  default     = "admin@localhost"
}

variable "langfuse_admin_password" {
  description = "Admin user password for Langfuse web UI"
  type        = string
  sensitive   = true
  default     = ""
}
