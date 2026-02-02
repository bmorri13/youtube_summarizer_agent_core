# YouTube Analyzer Agent - Docker Image
# Multi-stage build using Chainguard images for security
# Works for both local development and AWS Lambda deployment

# =============================================================================
# Stage 1: Build dependencies
# =============================================================================
FROM cgr.dev/chainguard/python:latest-dev AS builder

WORKDIR /app

# Copy requirements first for better layer caching
COPY requirements.txt .

# Install dependencies to a separate directory
RUN pip install --no-cache-dir -r requirements.txt --target /app/deps

# Install AWS Lambda Runtime Interface Client
RUN pip install --no-cache-dir awslambdaric --target /app/deps

# Install OTEL bootstrap dependencies
RUN pip install --no-cache-dir \
    opentelemetry-instrumentation \
    opentelemetry-distro \
    --target /app/deps

# Run opentelemetry-bootstrap to install auto-instrumentation packages
ENV PYTHONPATH=/app/deps
RUN python -m opentelemetry.instrumentation.bootstrap -a install || true

# =============================================================================
# Stage 2: Runtime (minimal Chainguard image, runs as non-root)
# =============================================================================
FROM cgr.dev/chainguard/python:latest

WORKDIR /app

# Copy installed dependencies from builder
COPY --from=builder /app/deps /app/deps

# Copy application code
COPY agent.py .
COPY lambda_handler.py .
COPY observability.py .
COPY tools/ ./tools/

# Set Python path to include dependencies
ENV PYTHONPATH=/app/deps
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Chainguard images run as non-root (uid 65532) by default
# Explicitly set USER to satisfy security scanners
USER nonroot

# Use opentelemetry-instrument wrapper for ADOT auto-instrumentation
# Then invoke the Lambda Runtime Interface Client
ENTRYPOINT ["python", "-m", "opentelemetry.instrumentation.auto_instrumentation", "python", "-m", "awslambdaric"]
CMD ["lambda_handler.handler"]
