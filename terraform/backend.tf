# Backend configuration for Terraform state
# This file is configured after running the bootstrap workflow
#
# To set up the backend:
# 1. Run the bootstrap workflow (.github/workflows/bootstrap.yml)
# 2. Copy the bucket name and table name from the outputs
# 3. Update the values below
# 4. Run: terraform init -migrate-state

terraform {
  backend "s3" {
    # These values will be populated by the bootstrap workflow output
    # Update with your actual values after running bootstrap
    bucket         = "youtube-analyzer-terraform-state-ACCOUNT_ID"
    key            = "prod/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "youtube-analyzer-terraform-locks"
    encrypt        = true
  }
}
