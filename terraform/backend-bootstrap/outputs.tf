output "terraform_state_bucket" {
  description = "S3 bucket name for Terraform state"
  value       = aws_s3_bucket.terraform_state.id
}

output "terraform_state_bucket_arn" {
  description = "S3 bucket ARN for Terraform state"
  value       = aws_s3_bucket.terraform_state.arn
}

output "terraform_locks_table" {
  description = "DynamoDB table name for Terraform state locking"
  value       = aws_dynamodb_table.terraform_locks.name
}

output "terraform_locks_table_arn" {
  description = "DynamoDB table ARN for Terraform state locking"
  value       = aws_dynamodb_table.terraform_locks.arn
}

output "github_actions_role_arn" {
  description = "IAM role ARN for GitHub Actions (add this to GitHub Secrets as AWS_ROLE_ARN)"
  value       = aws_iam_role.github_actions.arn
}

output "github_oidc_provider_arn" {
  description = "GitHub OIDC provider ARN"
  value       = aws_iam_openid_connect_provider.github.arn
}

output "aws_account_id" {
  description = "AWS Account ID"
  value       = data.aws_caller_identity.current.account_id
}

output "backend_config" {
  description = "Backend configuration to add to terraform/backend.tf"
  value       = <<-EOT
    # Add this to terraform/backend.tf
    terraform {
      backend "s3" {
        bucket         = "${aws_s3_bucket.terraform_state.id}"
        key            = "prod/terraform.tfstate"
        region         = "${var.aws_region}"
        dynamodb_table = "${aws_dynamodb_table.terraform_locks.name}"
        encrypt        = true
      }
    }
  EOT
}

output "next_steps" {
  description = "Instructions for completing setup"
  value       = <<-EOT

    ========================================
    BOOTSTRAP COMPLETE - NEXT STEPS
    ========================================

    1. Add the following GitHub Secrets:
       - AWS_ROLE_ARN: ${aws_iam_role.github_actions.arn}
       - ANTHROPIC_API_KEY: (your Anthropic API key)
       - SLACK_WEBHOOK_URL: (optional, for notifications)
       - MONITOR_CHANNEL_URLS: (comma-separated YouTube channel URLs)

    2. DELETE the temporary AWS credentials from GitHub Secrets:
       - AWS_ACCESS_KEY_ID
       - AWS_SECRET_ACCESS_KEY

    3. Update terraform/backend.tf with the backend configuration above

    4. Push to main branch to trigger deployment

    ========================================
  EOT
}
