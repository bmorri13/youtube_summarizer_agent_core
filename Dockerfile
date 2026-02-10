# YouTube Analyzer Agent - Docker Image
# Works for both local development and AWS Lambda deployment

# Use AWS Lambda Python base image for Lambda compatibility
FROM public.ecr.aws/lambda/python:3.11

# Set working directory
WORKDIR ${LAMBDA_TASK_ROOT}

# Install build tools needed for numpy (transitive dep from langchain-aws)
RUN yum install -y gcc gcc-c++ && yum clean all

# Copy requirements first for better layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install ADOT auto-instrumentation packages
RUN opentelemetry-bootstrap -a install || true

# Copy application code
COPY agent.py .
COPY lambda_handler.py .
COPY observability.py .
COPY tools/ ./tools/

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Note: USER directive is intentionally omitted for Lambda compatibility.
# Lambda runs containers in a secure sandbox with its own user isolation
# (sbx_user1051), regardless of the container's USER setting.
# Adding USER here breaks Lambda's runtime initialization.
# nosemgrep: dockerfile.security.missing-user, dockerfile.security.missing-user-entrypoint

# Use opentelemetry-instrument wrapper for ADOT auto-instrumentation
ENTRYPOINT ["opentelemetry-instrument"]
CMD ["python", "-m", "awslambdaric", "lambda_handler.handler"]
