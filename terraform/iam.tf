# IAM Role for Lambda
resource "aws_iam_role" "lambda" {
  name = "${var.project_name}-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

# CloudWatch Logs policy
resource "aws_iam_role_policy" "lambda_logs" {
  name = "${var.project_name}-logs"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ]
      Resource = ["${aws_cloudwatch_log_group.lambda.arn}:*"]
    }]
  })
}

# S3 policy (least privilege)
resource "aws_iam_role_policy" "lambda_s3" {
  name = "${var.project_name}-s3"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "s3:GetObject",
        "s3:PutObject",
        "s3:ListBucket"
      ]
      Resource = [
        aws_s3_bucket.notes.arn,
        "${aws_s3_bucket.notes.arn}/*"
      ]
    }]
  })
}

# X-Ray policy (conditional - for ADOT tracing)
resource "aws_iam_role_policy" "lambda_xray" {
  count = var.enable_observability ? 1 : 0
  name  = "${var.project_name}-xray"
  role  = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "xray:PutTraceSegments",
        "xray:PutTelemetryRecords"
      ]
      Resource = "*"
    }]
  })
}

# Custom CloudWatch log group for observability.py
resource "aws_iam_role_policy" "lambda_cloudwatch_custom" {
  count = var.enable_observability ? 1 : 0
  name  = "${var.project_name}-cloudwatch-custom"
  role  = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ]
      Resource = [
        "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/bedrock-agentcore/*"
      ]
    }]
  })
}

# Bedrock chatbot permissions (conditional on Knowledge Base)
resource "aws_iam_role_policy" "lambda_bedrock_chatbot" {
  count = var.enable_knowledge_base ? 1 : 0
  name  = "${var.project_name}-bedrock-chatbot"
  role  = aws_iam_role.lambda.id

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
          "arn:aws:bedrock:${var.aws_region}::foundation-model/anthropic.*",
          "arn:aws:bedrock:us.*::foundation-model/anthropic.*"
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
