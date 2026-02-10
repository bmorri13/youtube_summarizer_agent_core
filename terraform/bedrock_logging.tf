# Bedrock Model Invocation Logging
# Enables model call visibility in "GenAI Observability > Model Invocations"
# Conditional on enable_observability

# Log group for Bedrock model invocation logs
resource "aws_cloudwatch_log_group" "bedrock_invocation" {
  count             = var.enable_observability ? 1 : 0
  name              = "/aws/bedrock/model-invocation-logs"
  retention_in_days = var.log_retention_days
}

# IAM role for Bedrock to write to CloudWatch Logs
resource "aws_iam_role" "bedrock_logging" {
  count = var.enable_observability ? 1 : 0
  name  = "${var.project_name}-bedrock-logging"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "bedrock.amazonaws.com"
      }
      Action = "sts:AssumeRole"
      Condition = {
        StringEquals = {
          "aws:SourceAccount" = data.aws_caller_identity.current.account_id
        }
        ArnLike = {
          "aws:SourceArn" = "arn:aws:bedrock:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "bedrock_logging" {
  count = var.enable_observability ? 1 : 0
  name  = "${var.project_name}-bedrock-logging"
  role  = aws_iam_role.bedrock_logging[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ]
      Resource = "${aws_cloudwatch_log_group.bedrock_invocation[0].arn}:log-stream:aws/bedrock/modelinvocations"
    }]
  })
}

# Model invocation logging configuration (one per region)
resource "aws_bedrock_model_invocation_logging_configuration" "this" {
  count = var.enable_observability ? 1 : 0

  logging_config {
    embedding_data_delivery_enabled = false
    image_data_delivery_enabled     = false
    text_data_delivery_enabled      = true

    cloudwatch_config {
      log_group_name = aws_cloudwatch_log_group.bedrock_invocation[0].name
      role_arn       = aws_iam_role.bedrock_logging[0].arn
    }
  }

  depends_on = [aws_iam_role_policy.bedrock_logging]
}
