# Langfuse v3 Docker Compose — deployed via Terraform templatefile()
# All secrets are injected at deploy time; do not edit manually on the instance.

services:
  langfuse-worker:
    image: docker.io/langfuse/langfuse-worker:3
    restart: always
    depends_on: &langfuse-depends-on
      postgres:
        condition: service_healthy
      minio:
        condition: service_healthy
      redis:
        condition: service_healthy
      clickhouse:
        condition: service_healthy
    ports:
      - "127.0.0.1:3030:3030"
    environment: &langfuse-worker-env
      DATABASE_URL: postgresql://langfuse:${db_password}@postgres:5432/langfuse
      SALT: "${salt}"
      ENCRYPTION_KEY: "${encryption_key}"
      TELEMETRY_ENABLED: "false"
      LANGFUSE_ENABLE_EXPERIMENTAL_FEATURES: "true"
      # ClickHouse
      CLICKHOUSE_MIGRATION_URL: clickhouse://clickhouse:9000
      CLICKHOUSE_URL: http://clickhouse:8123
      CLICKHOUSE_USER: clickhouse
      CLICKHOUSE_PASSWORD: "${clickhouse_password}"
      CLICKHOUSE_CLUSTER_ENABLED: "false"
      # MinIO (S3-compatible blob storage)
      LANGFUSE_USE_AZURE_BLOB: "false"
      LANGFUSE_S3_EVENT_UPLOAD_BUCKET: langfuse
      LANGFUSE_S3_EVENT_UPLOAD_REGION: auto
      LANGFUSE_S3_EVENT_UPLOAD_ACCESS_KEY_ID: minio
      LANGFUSE_S3_EVENT_UPLOAD_SECRET_ACCESS_KEY: "${minio_password}"
      LANGFUSE_S3_EVENT_UPLOAD_ENDPOINT: http://minio:9000
      LANGFUSE_S3_EVENT_UPLOAD_FORCE_PATH_STYLE: "true"
      LANGFUSE_S3_EVENT_UPLOAD_PREFIX: events/
      LANGFUSE_S3_MEDIA_UPLOAD_BUCKET: langfuse
      LANGFUSE_S3_MEDIA_UPLOAD_REGION: auto
      LANGFUSE_S3_MEDIA_UPLOAD_ACCESS_KEY_ID: minio
      LANGFUSE_S3_MEDIA_UPLOAD_SECRET_ACCESS_KEY: "${minio_password}"
      LANGFUSE_S3_MEDIA_UPLOAD_ENDPOINT: http://minio:9000
      LANGFUSE_S3_MEDIA_UPLOAD_FORCE_PATH_STYLE: "true"
      LANGFUSE_S3_MEDIA_UPLOAD_PREFIX: media/
      LANGFUSE_S3_BATCH_EXPORT_ENABLED: "false"
      # Redis
      REDIS_HOST: redis
      REDIS_PORT: "6379"
      REDIS_AUTH: "${redis_password}"
      REDIS_TLS_ENABLED: "false"

  langfuse-web:
    image: docker.io/langfuse/langfuse:3
    restart: always
    depends_on: *langfuse-depends-on
    ports:
      - "3000:3000"
    environment:
      <<: *langfuse-worker-env
      NEXTAUTH_SECRET: "${nextauth_secret}"
      NEXTAUTH_URL: "${nextauth_url}"
      HOSTNAME: "0.0.0.0"
      PORT: "3000"
      # Auto-init: org, project, user, and API keys created on first boot
      LANGFUSE_INIT_ORG_ID: "${init_org_id}"
      LANGFUSE_INIT_ORG_NAME: YouTube Analyzer
      LANGFUSE_INIT_PROJECT_ID: "${init_project_id}"
      LANGFUSE_INIT_PROJECT_NAME: YouTube Analyzer
      LANGFUSE_INIT_PROJECT_PUBLIC_KEY: "${init_public_key}"
      LANGFUSE_INIT_PROJECT_SECRET_KEY: "${init_secret_key}"
      LANGFUSE_INIT_USER_EMAIL: "${init_user_email}"
      LANGFUSE_INIT_USER_NAME: Admin
      LANGFUSE_INIT_USER_PASSWORD: "${init_user_password}"
    healthcheck:
      test: ["CMD", "wget", "--no-verbose", "--tries=1", "--spider", "http://localhost:3000/api/public/health"]
      interval: 10s
      timeout: 5s
      retries: 10
      start_period: 30s

  clickhouse:
    image: docker.io/clickhouse/clickhouse-server
    restart: always
    user: "101:101"
    environment:
      CLICKHOUSE_DB: default
      CLICKHOUSE_USER: clickhouse
      CLICKHOUSE_PASSWORD: "${clickhouse_password}"
    volumes:
      - langfuse_clickhouse_data:/var/lib/clickhouse
      - langfuse_clickhouse_logs:/var/log/clickhouse-server
    ports:
      - "127.0.0.1:8123:8123"
      - "127.0.0.1:9000:9000"
    healthcheck:
      test: wget --no-verbose --tries=1 --spider http://localhost:8123/ping || exit 1
      interval: 5s
      timeout: 5s
      retries: 10
      start_period: 1s

  minio:
    image: cgr.dev/chainguard/minio
    restart: always
    entrypoint: sh
    command: -c 'mkdir -p /data/langfuse && minio server --address ":9000" --console-address ":9001" /data'
    environment:
      MINIO_ROOT_USER: minio
      MINIO_ROOT_PASSWORD: "${minio_password}"
    ports:
      - "127.0.0.1:9090:9000"
      - "127.0.0.1:9091:9001"
    volumes:
      - langfuse_minio_data:/data
    healthcheck:
      test: ["CMD", "mc", "ready", "local"]
      interval: 1s
      timeout: 5s
      retries: 5
      start_period: 1s

  redis:
    image: docker.io/redis:7
    restart: always
    command: >
      --requirepass ${redis_password}
      --maxmemory-policy noeviction
    ports:
      - "127.0.0.1:6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "-a", "${redis_password}", "ping"]
      interval: 3s
      timeout: 10s
      retries: 10

  postgres:
    image: docker.io/postgres:17
    restart: always
    environment:
      POSTGRES_USER: langfuse
      POSTGRES_PASSWORD: "${db_password}"
      POSTGRES_DB: langfuse
      TZ: UTC
      PGTZ: UTC
    ports:
      - "127.0.0.1:5432:5432"
    volumes:
      - langfuse_postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U langfuse"]
      interval: 3s
      timeout: 3s
      retries: 10

volumes:
  langfuse_postgres_data:
    driver: local
  langfuse_clickhouse_data:
    driver: local
  langfuse_clickhouse_logs:
    driver: local
  langfuse_minio_data:
    driver: local
