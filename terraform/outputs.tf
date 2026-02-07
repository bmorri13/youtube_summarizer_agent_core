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
  value       = var.enable_knowledge_base ? aws_s3vectors_vector_bucket.notes_vectors[0].vector_bucket_name : null
}

output "data_source_id" {
  description = "Bedrock Data Source ID"
  value       = var.enable_knowledge_base ? aws_bedrockagent_data_source.notes_s3[0].data_source_id : null
}

# Guardrail outputs
output "guardrail_id" {
  description = "Bedrock Guardrail ID for the chatbot"
  value       = var.enable_knowledge_base ? aws_bedrock_guardrail.chatbot[0].guardrail_id : null
}

output "guardrail_version" {
  description = "Bedrock Guardrail version for the chatbot"
  value       = var.enable_knowledge_base ? aws_bedrock_guardrail_version.chatbot[0].version : null
}

# ECS Fargate chatbot outputs
output "chatbot_ecr_repository_url" {
  description = "ECR repository URL for the chatbot image"
  value       = var.enable_knowledge_base ? aws_ecr_repository.chatbot[0].repository_url : null
}

output "chatbot_url" {
  description = "ALB URL for the chatbot (HTTP; HTTPS via Cloudflare)"
  value       = var.enable_knowledge_base ? "http://${aws_lb.chatbot[0].dns_name}" : null
}

output "chatbot_cluster_name" {
  description = "ECS cluster name for CI/CD deployments"
  value       = var.enable_knowledge_base ? aws_ecs_cluster.chatbot[0].name : null
}

output "chatbot_service_name" {
  description = "ECS service name for CI/CD deployments"
  value       = var.enable_knowledge_base ? aws_ecs_service.chatbot[0].name : null
}

# Langfuse outputs
output "langfuse_url" {
  description = "Langfuse URL (via ALB host-based routing)"
  value       = var.enable_langfuse ? "https://${var.langfuse_host_header}" : null
}

output "langfuse_ecr_repository_url" {
  description = "ECR repository URL for Langfuse image"
  value       = var.enable_langfuse ? aws_ecr_repository.langfuse[0].repository_url : null
}

output "langfuse_rds_endpoint" {
  description = "RDS endpoint for Langfuse PostgreSQL"
  value       = var.enable_langfuse ? aws_db_instance.langfuse[0].endpoint : null
  sensitive   = true
}
