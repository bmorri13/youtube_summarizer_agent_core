# Lambda function log group
resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${var.project_name}"
  retention_in_days = var.log_retention_days
}

# SNS Topic for alarms (optional)
resource "aws_sns_topic" "alarms" {
  count = var.enable_alarms ? 1 : 0
  name  = "${var.project_name}-alarms"
}

# Email subscription for alarms (optional)
resource "aws_sns_topic_subscription" "email" {
  count     = var.enable_alarms && var.alarm_email != "" ? 1 : 0
  topic_arn = aws_sns_topic.alarms[0].arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

# CloudWatch alarm for Lambda errors (optional)
resource "aws_cloudwatch_metric_alarm" "errors" {
  count               = var.enable_alarms ? 1 : 0
  alarm_name          = "${var.project_name}-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 3
  alarm_description   = "Lambda function error rate exceeds threshold"

  dimensions = {
    FunctionName = aws_lambda_function.main.function_name
  }

  alarm_actions = [aws_sns_topic.alarms[0].arn]
}

# CloudWatch alarm for Lambda throttles (optional)
resource "aws_cloudwatch_metric_alarm" "throttles" {
  count               = var.enable_alarms ? 1 : 0
  alarm_name          = "${var.project_name}-throttles"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Throttles"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 1
  alarm_description   = "Lambda function is being throttled"

  dimensions = {
    FunctionName = aws_lambda_function.main.function_name
  }

  alarm_actions = [aws_sns_topic.alarms[0].arn]
}

# =============================================================================
# Transaction Search / Application Signals Configuration
# Enables trace visibility in CloudWatch Application Signals / AgentCore
# =============================================================================

# CloudWatch Logs resource policy to allow X-Ray to write spans
resource "aws_cloudwatch_log_resource_policy" "xray_transaction_search" {
  count       = var.enable_observability ? 1 : 0
  policy_name = "${var.project_name}-xray-transaction-search"

  policy_document = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "TransactionSearchXRayAccess"
        Effect = "Allow"
        Principal = {
          Service = "xray.amazonaws.com"
        }
        Action = "logs:PutLogEvents"
        Resource = [
          "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:aws/spans:*",
          "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/application-signals/data:*"
        ]
        Condition = {
          ArnLike = {
            "aws:SourceArn" = "arn:aws:xray:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*"
          }
          StringEquals = {
            "aws:SourceAccount" = data.aws_caller_identity.current.account_id
          }
        }
      }
    ]
  })
}

# Enable Transaction Search via AWS CLI (no native Terraform resource yet)
resource "null_resource" "enable_transaction_search" {
  count = var.enable_observability ? 1 : 0

  # Re-run if observability setting changes or version bumped
  triggers = {
    enable_observability = var.enable_observability
    version              = "2" # Bump to force re-run
  }

  # Wait for the log resource policy to be created first
  depends_on = [aws_cloudwatch_log_resource_policy.xray_transaction_search]

  provisioner "local-exec" {
    command = <<-EOT
      # Enable CloudWatch Logs as trace destination
      aws xray update-trace-segment-destination --destination CloudWatchLogs --region ${var.aws_region} || true

      # Set indexing to 1% (free tier)
      aws xray update-indexing-rule --name "Default" --rule '{"Probabilistic": {"DesiredSamplingPercentage": 1}}' --region ${var.aws_region} || true

      echo "Transaction Search enabled for region ${var.aws_region}"
    EOT
  }
}
