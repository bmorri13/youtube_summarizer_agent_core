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
        "xray:PutTelemetryRecords",
        "xray:GetSamplingRules",
        "xray:GetSamplingTargets"
      ]
      Resource = "*"
    }]
  })
}

# AgentCore log group write access (conditional - for GenAI Observability dashboard)
resource "aws_iam_role_policy" "lambda_agentcore_logs" {
  count = var.enable_observability ? 1 : 0
  name  = "${var.project_name}-agentcore-logs"
  role  = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "logs:CreateLogStream",
        "logs:PutLogEvents",
        "logs:DescribeLogGroups",
        "logs:DescribeLogStreams"
      ]
      Resource = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/bedrock-agentcore/runtimes/*:*"
    }]
  })
}

# Bedrock agent permissions (always needed - agent uses Bedrock for LLM calls)
resource "aws_iam_role_policy" "lambda_bedrock_agent" {
  name = "${var.project_name}-bedrock-agent"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ]
      Resource = [
        "arn:aws:bedrock:*::foundation-model/anthropic.*",
        "arn:aws:bedrock:${var.aws_region}:${data.aws_caller_identity.current.account_id}:inference-profile/us.anthropic.*"
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
          "bedrock:ApplyGuardrail",
          "bedrock:GetGuardrail"
        ]
        Resource = [aws_bedrock_guardrail.chatbot[0].guardrail_arn]
      }
    ]
  })
}
