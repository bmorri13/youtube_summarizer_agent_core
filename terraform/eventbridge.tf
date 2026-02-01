# EventBridge rule for scheduled monitoring
resource "aws_cloudwatch_event_rule" "scheduled" {
  count               = var.enable_scheduled_monitoring ? 1 : 0
  name                = "${var.project_name}-scheduled"
  description         = "Trigger YouTube channel monitoring"
  schedule_expression = var.schedule_expression
}

# EventBridge target - Lambda function
resource "aws_cloudwatch_event_target" "lambda" {
  count     = var.enable_scheduled_monitoring ? 1 : 0
  rule      = aws_cloudwatch_event_rule.scheduled[0].name
  target_id = "lambda"
  arn       = aws_lambda_function.main.arn

  input = jsonencode({
    channel_urls = split(",", var.monitor_channel_urls)
  })
}

# Lambda permission for EventBridge
resource "aws_lambda_permission" "eventbridge" {
  count         = var.enable_scheduled_monitoring ? 1 : 0
  statement_id  = "AllowEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.main.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.scheduled[0].arn
}
