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
        # Application config (uses Bedrock via IAM, no API key needed)
        NOTES_BACKEND        = "s3"
        NOTES_S3_BUCKET      = aws_s3_bucket.notes.id
        CLAUDE_MODEL         = var.claude_model
        SLACK_WEBHOOK_URL    = var.slack_webhook_url
        MONITOR_CHANNEL_URLS = var.monitor_channel_urls
        # Note: AWS_REGION is automatically provided by Lambda
      },
      var.enable_observability ? {
        # Collector-less ADOT: send OTLP traces directly to X-Ray HTTPS endpoint
        # (container Lambda has no ADOT Layer/collector, and UDP daemon has 64KB limit)
        OTEL_SERVICE_NAME                       = var.project_name
        OTEL_PYTHON_DISTRO                      = "aws_distro"
        OTEL_PYTHON_CONFIGURATOR                = "aws_configurator"
        OTEL_TRACES_EXPORTER                    = "otlp"
        OTEL_EXPORTER_OTLP_TRACES_ENDPOINT      = "https://xray.${var.aws_region}.amazonaws.com/v1/traces"
        OTEL_EXPORTER_OTLP_TRACES_PROTOCOL      = "http/protobuf"
        OTEL_METRICS_EXPORTER                   = "none"
        OTEL_LOGS_EXPORTER                      = "none"
        OTEL_RESOURCE_ATTRIBUTES                = "service.name=${var.project_name},aws.log.group.names=/aws/lambda/${var.project_name}"
        OTEL_PYTHON_DISABLED_INSTRUMENTATIONS   = "aws-lambda"
        # Truncate span attributes — full-fidelity traces are in Langfuse
        OTEL_SPAN_ATTRIBUTE_VALUE_LENGTH_LIMIT  = "4096"
        OTEL_SPAN_ATTRIBUTE_COUNT_LIMIT         = "128"
        LOG_LEVEL                               = "INFO"
      } : {},
      var.enable_knowledge_base ? {
        # RAG Chatbot configuration
        KNOWLEDGE_BASE_ID         = aws_bedrockagent_knowledge_base.notes[0].id
        CHATBOT_MODEL_ID          = var.chatbot_model_id
        BEDROCK_GUARDRAIL_ID      = aws_bedrock_guardrail.chatbot[0].guardrail_id
        BEDROCK_GUARDRAIL_VERSION = aws_bedrock_guardrail_version.chatbot[0].version
        KB_MAX_RESULTS            = "5"
      } : {},
      var.enable_langfuse ? {
        LANGFUSE_HOST       = "https://${var.langfuse_host_header}"
        LANGFUSE_PUBLIC_KEY = local.langfuse_public_key
        LANGFUSE_SECRET_KEY = local.langfuse_secret_key
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
