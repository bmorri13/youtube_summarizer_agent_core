# YouTube Analyzer Agent - Docker Image
# Works for both local development and AWS Lambda deployment

# Use AWS Lambda Python base image for Lambda compatibility
FROM public.ecr.aws/lambda/python:3.12

# Set working directory
WORKDIR ${LAMBDA_TASK_ROOT}

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
#
# The nosemgrep annotations below must sit on the line immediately preceding the
# offending instruction and use the full rule ID, or they are ignored.

# Use opentelemetry-instrument wrapper for ADOT auto-instrumentation
# nosemgrep: dockerfile.security.missing-user-entrypoint.missing-user-entrypoint
ENTRYPOINT ["opentelemetry-instrument"]
# nosemgrep: dockerfile.security.missing-user.missing-user
CMD ["python", "-m", "awslambdaric", "lambda_handler.handler"]
