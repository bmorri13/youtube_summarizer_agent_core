output "lambda_function_name" {
  description = "Name of the Lambda function"
  value       = aws_lambda_function.main.function_name
}

output "lambda_function_arn" {
  description = "ARN of the Lambda function"
  value       = aws_lambda_function.main.arn
}

output "s3_bucket_name" {
  description = "Name of the S3 bucket for notes"
  value       = aws_s3_bucket.notes.id
}

output "ecr_repository_url" {
  description = "URL of the ECR repository"
  value       = aws_ecr_repository.main.repository_url
}

output "cloudwatch_log_group" {
  description = "CloudWatch log group for Lambda"
  value       = aws_cloudwatch_log_group.lambda.name
}

output "agent_log_group" {
  description = "CloudWatch log group for agent observability"
  value       = var.enable_observability ? aws_cloudwatch_log_group.agent[0].name : null
}
