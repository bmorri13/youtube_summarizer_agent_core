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

variable "schedule_expression" {
  description = "EventBridge schedule expression for monitoring"
  type        = string
  default     = "rate(1 hour)"
}

variable "enable_scheduled_monitoring" {
  description = "Enable scheduled channel monitoring"
  type        = bool
  default     = false
}

variable "enable_observability" {
  description = "Enable ADOT observability and CloudWatch custom logging"
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
