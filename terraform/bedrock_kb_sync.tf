# Auto-sync infrastructure for Bedrock Knowledge Base
# S3 event notification triggers Lambda to start ingestion job

# Lambda function to trigger KB sync on new notes
resource "aws_lambda_function" "kb_sync" {
  count         = var.enable_knowledge_base ? 1 : 0
  function_name = "${var.project_name}-kb-sync"
  role          = aws_iam_role.kb_sync_lambda[0].arn
  handler       = "index.handler"
  runtime       = "python3.12"
  timeout       = 30

  filename         = data.archive_file.kb_sync_lambda[0].output_path
  source_code_hash = data.archive_file.kb_sync_lambda[0].output_base64sha256

  environment {
    variables = {
      KNOWLEDGE_BASE_ID = aws_bedrockagent_knowledge_base.notes[0].id
      DATA_SOURCE_ID    = aws_bedrockagent_data_source.notes_s3[0].data_source_id
    }
  }

  depends_on = [aws_cloudwatch_log_group.kb_sync]
}

# Inline Lambda code for KB sync
data "archive_file" "kb_sync_lambda" {
  count       = var.enable_knowledge_base ? 1 : 0
  type        = "zip"
  output_path = "${path.module}/kb_sync_lambda.zip"

  source {
    content  = <<-EOF
      import boto3
      import os

      def handler(event, context):
          # Filter to only process .md files in notes/ prefix
          for record in event.get('Records', []):
              key = record.get('s3', {}).get('object', {}).get('key', '')
              if key.startswith('notes/') and key.endswith('.md'):
                  client = boto3.client('bedrock-agent')
                  response = client.start_ingestion_job(
                      knowledgeBaseId=os.environ['KNOWLEDGE_BASE_ID'],
                      dataSourceId=os.environ['DATA_SOURCE_ID']
                  )
                  print(f"Started ingestion job: {response['ingestionJob']['ingestionJobId']}")
                  return {'statusCode': 200, 'body': 'Sync started'}

          print("Skipped - not a notes/*.md file")
          return {'statusCode': 200, 'body': 'Skipped'}
    EOF
    filename = "index.py"
  }
}

# Lambda permission - Allow S3 to invoke
resource "aws_lambda_permission" "s3_sync" {
  count         = var.enable_knowledge_base ? 1 : 0
  statement_id  = "AllowS3Invoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.kb_sync[0].function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.notes.arn
}

# S3 bucket notification - Direct Lambda trigger on ObjectCreated
resource "aws_s3_bucket_notification" "notes_kb_sync" {
  count  = var.enable_knowledge_base ? 1 : 0
  bucket = aws_s3_bucket.notes.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.kb_sync[0].arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "notes/"
    filter_suffix       = ".md"
  }

  depends_on = [aws_lambda_permission.s3_sync]
}

# IAM Role for KB Sync Lambda
resource "aws_iam_role" "kb_sync_lambda" {
  count = var.enable_knowledge_base ? 1 : 0
  name  = "${var.project_name}-kb-sync-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })
}

# IAM Policy - Bedrock StartIngestionJob
resource "aws_iam_role_policy" "kb_sync_bedrock" {
  count = var.enable_knowledge_base ? 1 : 0
  name  = "bedrock-start-ingestion"
  role  = aws_iam_role.kb_sync_lambda[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["bedrock:StartIngestionJob"]
      Resource = [aws_bedrockagent_knowledge_base.notes[0].arn]
    }]
  })
}

# Attach basic Lambda execution role for CloudWatch Logs
resource "aws_iam_role_policy_attachment" "kb_sync_logs" {
  count      = var.enable_knowledge_base ? 1 : 0
  role       = aws_iam_role.kb_sync_lambda[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# CloudWatch Log Group for Sync Lambda
resource "aws_cloudwatch_log_group" "kb_sync" {
  count             = var.enable_knowledge_base ? 1 : 0
  name              = "/aws/lambda/${var.project_name}-kb-sync"
  retention_in_days = var.log_retention_days
}
