#!/usr/bin/env python
"""
Deploy YouTube Analyzer to AWS Lambda using Docker container.

This script:
1. Builds the Docker image
2. Pushes to Amazon ECR
3. Creates/updates the Lambda function
4. Optionally sets up API Gateway

Prerequisites:
- Docker installed and running
- AWS CLI configured (aws configure)
- Appropriate IAM permissions

Usage:
    python deploy_lambda.py                    # Deploy with defaults
    python deploy_lambda.py --create-api       # Also create API Gateway
    python deploy_lambda.py --function-name my-analyzer  # Custom name
"""

import argparse
import json
import os
import subprocess
import sys
import time


# Configuration
DEFAULT_FUNCTION_NAME = "youtube-analyzer"
DEFAULT_REGION = "us-east-1"
DEFAULT_MEMORY = 1024  # MB
DEFAULT_TIMEOUT = 300  # seconds (5 minutes)


def run_command(cmd: list, capture_output: bool = True) -> subprocess.CompletedProcess:
    """Run a shell command and handle errors."""
    print(f"  → {' '.join(cmd)[:80]}...")
    result = subprocess.run(cmd, capture_output=capture_output, text=True)
    if result.returncode != 0:
        print(f"  ✗ Command failed: {result.stderr}")
        sys.exit(1)
    return result


def get_aws_account_id() -> str:
    """Get AWS account ID."""
    result = run_command(["aws", "sts", "get-caller-identity", "--query", "Account", "--output", "text"])
    return result.stdout.strip()


def get_aws_region() -> str:
    """Get configured AWS region."""
    result = run_command(["aws", "configure", "get", "region"])
    return result.stdout.strip() or DEFAULT_REGION


def ecr_login(region: str, account_id: str):
    """Login to Amazon ECR."""
    print("\n📦 Logging into ECR...")
    
    ecr_url = f"{account_id}.dkr.ecr.{region}.amazonaws.com"
    
    # Get login password
    result = run_command([
        "aws", "ecr", "get-login-password", "--region", region
    ])
    password = result.stdout.strip()
    
    # Docker login
    login_cmd = subprocess.run(
        ["docker", "login", "--username", "AWS", "--password-stdin", ecr_url],
        input=password,
        capture_output=True,
        text=True
    )
    
    if login_cmd.returncode != 0:
        print(f"  ✗ Docker login failed: {login_cmd.stderr}")
        sys.exit(1)
    
    print("  ✓ ECR login successful")
    return ecr_url


def create_ecr_repository(repo_name: str, region: str):
    """Create ECR repository if it doesn't exist."""
    print(f"\n📦 Checking ECR repository: {repo_name}")
    
    # Check if repo exists
    result = subprocess.run(
        ["aws", "ecr", "describe-repositories", "--repository-names", repo_name, "--region", region],
        capture_output=True,
        text=True
    )
    
    if result.returncode != 0:
        print(f"  Creating repository...")
        run_command([
            "aws", "ecr", "create-repository",
            "--repository-name", repo_name,
            "--region", region,
            "--image-scanning-configuration", "scanOnPush=true"
        ])
        print(f"  ✓ Repository created")
    else:
        print(f"  ✓ Repository exists")


def build_and_push_image(ecr_url: str, repo_name: str, tag: str = "latest"):
    """Build Docker image and push to ECR."""
    
    image_uri = f"{ecr_url}/{repo_name}:{tag}"
    
    print(f"\n🔨 Building Docker image...")
    run_command([
        "docker", "build",
        "-t", f"{repo_name}:{tag}",
        "-f", "Dockerfile",
        "."
    ], capture_output=False)
    print("  ✓ Build complete")
    
    print(f"\n🏷️  Tagging image...")
    run_command(["docker", "tag", f"{repo_name}:{tag}", image_uri])
    print(f"  ✓ Tagged as {image_uri}")
    
    print(f"\n⬆️  Pushing to ECR...")
    run_command(["docker", "push", image_uri], capture_output=False)
    print("  ✓ Push complete")
    
    return image_uri


def create_lambda_role(role_name: str) -> str:
    """Create IAM role for Lambda if it doesn't exist."""
    print(f"\n🔐 Checking IAM role: {role_name}")
    
    # Check if role exists
    result = subprocess.run(
        ["aws", "iam", "get-role", "--role-name", role_name],
        capture_output=True,
        text=True
    )
    
    if result.returncode == 0:
        role_data = json.loads(result.stdout)
        print("  ✓ Role exists")
        return role_data["Role"]["Arn"]
    
    print("  Creating role...")
    
    # Trust policy for Lambda
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "lambda.amazonaws.com"},
            "Action": "sts:AssumeRole"
        }]
    }
    
    # Create role
    result = run_command([
        "aws", "iam", "create-role",
        "--role-name", role_name,
        "--assume-role-policy-document", json.dumps(trust_policy)
    ])
    role_data = json.loads(result.stdout)
    role_arn = role_data["Role"]["Arn"]
    
    # Attach basic Lambda execution policy
    run_command([
        "aws", "iam", "attach-role-policy",
        "--role-name", role_name,
        "--policy-arn", "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
    ])
    
    # Attach S3 access if using S3 notes backend
    run_command([
        "aws", "iam", "attach-role-policy",
        "--role-name", role_name,
        "--policy-arn", "arn:aws:iam::aws:policy/AmazonS3FullAccess"
    ])
    
    print("  ✓ Role created")
    
    # Wait for role to propagate
    print("  Waiting for role propagation...")
    time.sleep(10)
    
    return role_arn


def create_or_update_lambda(
    function_name: str,
    image_uri: str,
    role_arn: str,
    region: str,
    memory: int,
    timeout: int,
    env_vars: dict
):
    """Create or update Lambda function."""
    print(f"\n⚡ Deploying Lambda function: {function_name}")
    
    # Check if function exists
    result = subprocess.run(
        ["aws", "lambda", "get-function", "--function-name", function_name, "--region", region],
        capture_output=True,
        text=True
    )
    
    env_json = json.dumps({"Variables": env_vars})
    
    if result.returncode == 0:
        # Update existing function
        print("  Updating function code...")
        run_command([
            "aws", "lambda", "update-function-code",
            "--function-name", function_name,
            "--image-uri", image_uri,
            "--region", region
        ])
        
        # Wait for update to complete
        print("  Waiting for update...")
        run_command([
            "aws", "lambda", "wait", "function-updated",
            "--function-name", function_name,
            "--region", region
        ])
        
        print("  Updating function configuration...")
        run_command([
            "aws", "lambda", "update-function-configuration",
            "--function-name", function_name,
            "--memory-size", str(memory),
            "--timeout", str(timeout),
            "--environment", env_json,
            "--region", region
        ])
        
        print("  ✓ Function updated")
    else:
        # Create new function
        print("  Creating new function...")
        run_command([
            "aws", "lambda", "create-function",
            "--function-name", function_name,
            "--package-type", "Image",
            "--code", f"ImageUri={image_uri}",
            "--role", role_arn,
            "--memory-size", str(memory),
            "--timeout", str(timeout),
            "--environment", env_json,
            "--region", region
        ])
        
        print("  Waiting for function to be active...")
        run_command([
            "aws", "lambda", "wait", "function-active",
            "--function-name", function_name,
            "--region", region
        ])
        
        print("  ✓ Function created")


def create_api_gateway(function_name: str, region: str, account_id: str):
    """Create HTTP API Gateway for the Lambda function."""
    print(f"\n🌐 Creating API Gateway...")
    
    api_name = f"{function_name}-api"
    
    # Create HTTP API
    result = run_command([
        "aws", "apigatewayv2", "create-api",
        "--name", api_name,
        "--protocol-type", "HTTP",
        "--region", region
    ])
    api_data = json.loads(result.stdout)
    api_id = api_data["ApiId"]
    
    # Create Lambda integration
    lambda_arn = f"arn:aws:lambda:{region}:{account_id}:function:{function_name}"
    
    result = run_command([
        "aws", "apigatewayv2", "create-integration",
        "--api-id", api_id,
        "--integration-type", "AWS_PROXY",
        "--integration-uri", lambda_arn,
        "--payload-format-version", "2.0",
        "--region", region
    ])
    integration_data = json.loads(result.stdout)
    integration_id = integration_data["IntegrationId"]
    
    # Create route
    run_command([
        "aws", "apigatewayv2", "create-route",
        "--api-id", api_id,
        "--route-key", "POST /analyze",
        "--target", f"integrations/{integration_id}",
        "--region", region
    ])
    
    # Create stage
    run_command([
        "aws", "apigatewayv2", "create-stage",
        "--api-id", api_id,
        "--stage-name", "$default",
        "--auto-deploy",
        "--region", region
    ])
    
    # Add Lambda permission for API Gateway
    run_command([
        "aws", "lambda", "add-permission",
        "--function-name", function_name,
        "--statement-id", "apigateway-invoke",
        "--action", "lambda:InvokeFunction",
        "--principal", "apigateway.amazonaws.com",
        "--source-arn", f"arn:aws:execute-api:{region}:{account_id}:{api_id}/*",
        "--region", region
    ])
    
    api_endpoint = f"https://{api_id}.execute-api.{region}.amazonaws.com"
    print(f"  ✓ API Gateway created: {api_endpoint}")
    
    return api_endpoint


def main():
    parser = argparse.ArgumentParser(description="Deploy YouTube Analyzer to AWS Lambda")
    parser.add_argument("--function-name", default=DEFAULT_FUNCTION_NAME, help="Lambda function name")
    parser.add_argument("--region", help="AWS region (default: from AWS config)")
    parser.add_argument("--memory", type=int, default=DEFAULT_MEMORY, help="Lambda memory in MB")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="Lambda timeout in seconds")
    parser.add_argument("--create-api", action="store_true", help="Create API Gateway")
    args = parser.parse_args()
    
    print("=" * 60)
    print("YouTube Analyzer - Lambda Deployment")
    print("=" * 60)
    
    # Get AWS info
    account_id = get_aws_account_id()
    region = args.region or get_aws_region()
    
    print(f"\n📋 Configuration:")
    print(f"   Account ID: {account_id}")
    print(f"   Region: {region}")
    print(f"   Function: {args.function_name}")
    print(f"   Memory: {args.memory} MB")
    print(f"   Timeout: {args.timeout} seconds")
    
    # Check for required environment variables
    required_env = ["ANTHROPIC_API_KEY"]
    missing = [v for v in required_env if not os.getenv(v)]
    if missing:
        print(f"\n❌ Missing required environment variables: {missing}")
        print("   Set them before deploying:")
        print("   export ANTHROPIC_API_KEY=your-key")
        sys.exit(1)
    
    # Prepare environment variables for Lambda
    env_vars = {
        "ANTHROPIC_API_KEY": os.getenv("ANTHROPIC_API_KEY"),
        "NOTES_BACKEND": os.getenv("NOTES_BACKEND", "local"),
        "NOTES_LOCAL_DIR": "/tmp/notes",  # Lambda writable directory
    }
    
    if os.getenv("SLACK_WEBHOOK_URL"):
        env_vars["SLACK_WEBHOOK_URL"] = os.getenv("SLACK_WEBHOOK_URL")
    if os.getenv("SLACK_BOT_TOKEN"):
        env_vars["SLACK_BOT_TOKEN"] = os.getenv("SLACK_BOT_TOKEN")
    if os.getenv("NOTES_S3_BUCKET"):
        env_vars["NOTES_S3_BUCKET"] = os.getenv("NOTES_S3_BUCKET")
        env_vars["NOTES_BACKEND"] = "s3"
    
    repo_name = args.function_name
    role_name = f"{args.function_name}-role"
    
    # Deploy steps
    ecr_url = ecr_login(region, account_id)
    create_ecr_repository(repo_name, region)
    image_uri = build_and_push_image(ecr_url, repo_name)
    role_arn = create_lambda_role(role_name)
    create_or_update_lambda(
        args.function_name,
        image_uri,
        role_arn,
        region,
        args.memory,
        args.timeout,
        env_vars
    )
    
    api_endpoint = None
    if args.create_api:
        api_endpoint = create_api_gateway(args.function_name, region, account_id)
    
    # Print summary
    print("\n" + "=" * 60)
    print("✅ Deployment Complete!")
    print("=" * 60)
    print(f"\nLambda Function: {args.function_name}")
    print(f"Region: {region}")
    
    if api_endpoint:
        print(f"\nAPI Endpoint: {api_endpoint}")
        print(f"\nTest with:")
        print(f'  curl -X POST {api_endpoint}/analyze \\')
        print(f'    -H "Content-Type: application/json" \\')
        print(f'    -d \'{{"video_url": "https://youtube.com/watch?v=VIDEO_ID"}}\'')
    else:
        print(f"\nTest with AWS CLI:")
        print(f'  aws lambda invoke --function-name {args.function_name} \\')
        print(f'    --payload \'{{"video_url": "https://youtube.com/watch?v=VIDEO_ID"}}\' \\')
        print(f'    --cli-binary-format raw-in-base64-out \\')
        print(f'    response.json && cat response.json')
    
    print("\n💡 Tip: Add --create-api flag to create an HTTP endpoint")


if __name__ == "__main__":
    main()
