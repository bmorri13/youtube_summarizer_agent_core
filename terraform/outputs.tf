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

# Knowledge Base outputs
output "knowledge_base_id" {
  description = "Bedrock Knowledge Base ID"
  value       = var.enable_knowledge_base ? aws_bedrockagent_knowledge_base.notes[0].id : null
}

output "knowledge_base_arn" {
  description = "Bedrock Knowledge Base ARN for querying"
  value       = var.enable_knowledge_base ? aws_bedrockagent_knowledge_base.notes[0].arn : null
}

output "vector_bucket_name" {
  description = "S3 Vector bucket name"
  value       = var.enable_knowledge_base ? aws_s3vectors_vector_bucket.notes_vectors[0].bucket_name : null
}

output "data_source_id" {
  description = "Bedrock Data Source ID"
  value       = var.enable_knowledge_base ? aws_bedrockagent_data_source.notes_s3[0].data_source_id : null
}
