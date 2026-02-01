# Lambda function log group
resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${var.project_name}"
  retention_in_days = var.log_retention_days
}

# Agent observability log group (for custom structured logs)
resource "aws_cloudwatch_log_group" "agent" {
  count             = var.enable_observability ? 1 : 0
  name              = "/aws/bedrock-agentcore/${var.project_name}"
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
