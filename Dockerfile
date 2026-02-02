# YouTube Analyzer Agent - Docker Image
# Works for both local development and AWS Lambda deployment

# Use AWS Lambda Python base image for Lambda compatibility
FROM public.ecr.aws/lambda/python:3.11

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

# Use opentelemetry-instrument wrapper for ADOT auto-instrumentation
ENTRYPOINT ["opentelemetry-instrument"]
CMD ["python", "-m", "awslambdaric", "lambda_handler.handler"]
