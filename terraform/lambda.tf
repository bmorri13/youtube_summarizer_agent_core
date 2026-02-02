# Lambda Function with ADOT & AgentCore Observability
resource "aws_lambda_function" "main" {
  function_name = var.project_name
  role          = aws_iam_role.lambda.arn
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.main.repository_url}:latest"
  memory_size   = var.lambda_memory_size
  timeout       = var.lambda_timeout

  environment {
    variables = merge(
      {
        # Application config
        ANTHROPIC_API_KEY    = var.anthropic_api_key
        NOTES_BACKEND        = "s3"
        NOTES_S3_BUCKET      = aws_s3_bucket.notes.id
        CLAUDE_MODEL         = var.claude_model
        SLACK_WEBHOOK_URL    = var.slack_webhook_url
        MONITOR_CHANNEL_URLS = var.monitor_channel_urls
        # Note: AWS_REGION is automatically provided by Lambda
      },
      var.enable_observability ? {
        # AWS ADOT configuration for Bedrock AgentCore Observability
        OTEL_SERVICE_NAME             = var.project_name
        OTEL_PYTHON_DISTRO            = "aws_distro"
        OTEL_PYTHON_CONFIGURATOR      = "aws_configurator"
        OTEL_EXPORTER_OTLP_PROTOCOL   = "http/protobuf"
        OTEL_TRACES_EXPORTER          = "otlp"
        OTEL_METRICS_EXPORTER         = "none"
        OTEL_LOGS_EXPORTER            = "none"

        # CloudWatch logging
        CLOUDWATCH_LOG_GROUP          = "/aws/bedrock-agentcore/${var.project_name}"
        LOG_LEVEL                     = "INFO"
        AGENT_OBSERVABILITY_ENABLED   = "true"
      } : {}
    )
  }

  tracing_config {
    mode = var.enable_observability ? "Active" : "PassThrough"
  }

  depends_on = [
    aws_cloudwatch_log_group.lambda,
    aws_iam_role_policy.lambda_logs,
    aws_iam_role_policy.lambda_s3,
  ]

  lifecycle {
    ignore_changes = [image_uri]
  }
}
