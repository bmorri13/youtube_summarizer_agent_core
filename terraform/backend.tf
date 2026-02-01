terraform {
  backend "s3" {
    bucket         = "youtube-analyzer-terraform-state-278862850009"
    key            = "prod/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "youtube-analyzer-terraform-locks"
    encrypt        = true
  }
}
