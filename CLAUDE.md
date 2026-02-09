# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

YouTube Analyzer Agent - an AI agent that analyzes YouTube videos by fetching transcripts, generating summaries, saving notes, and sending Slack notifications. Uses the Anthropic Python SDK with a manual tool-calling loop (not the Node.js-based claude-agent-sdk).

## Development Commands

```bash
# Setup
python -m venv venv && source venv/bin/activate && pip install -r requirements.txt

# Run agent locally (loads .env automatically)
python agent.py "https://www.youtube.com/watch?v=VIDEO_ID"

# Run agent on a channel (checks latest video)
python agent.py "https://www.youtube.com/@ChannelName"

# Docker services
docker-compose up local     # Interactive local dev
docker-compose up server    # HTTP server (port 8080)
docker-compose up chatbot   # RAG chatbot (port 8081)
docker-compose up lambda    # Lambda emulation (port 9000)

# Test Lambda locally
curl -X POST "http://localhost:9000/2015-03-31/functions/function/invocations" \
  -d '{"video_url": "https://youtube.com/watch?v=VIDEO_ID"}'

# Terraform deployment
cd terraform && terraform init && terraform apply

# Manually trigger local fetcher (requires Tailscale access to home server)
ssh root@docker-compose-03 "cd /opt/docker/yt-transcript && docker compose run --rm fetcher python local_fetcher.py"
```

## Testing

There is no automated test suite. Manual testing is done by running the agent against real YouTube URLs.

## Architecture

### Agent Loop Pattern
The agent in `agent.py` implements a standard Anthropic tool-calling loop:

1. `SYSTEM_PROMPT` defines the agent's behavior and workflow
2. `ALL_TOOLS` (from `tools/__init__.py`) provides tool schemas to Claude
3. `run_agent()` loops until `stop_reason == "end_turn"` or max turns reached
4. `handle_tool_call()` dispatches tool executions and logs results

### Tools
Current tools in `tools/`:
- `youtube.py` - `get_transcript`: Fetch video transcript and metadata via `youtube-transcript-api`
- `channel.py` - `get_latest_channel_video`: Get latest video from a channel via RSS feed (filters out Shorts < 90s)
- `notes.py` - `save_note`: Save analysis to local/S3, track processed videos
- `slack.py` - `send_slack_notification`: Send Block Kit formatted notifications

Each tool module exports `TOOL_DEFINITION` (JSON schema) and a main function.

### Hybrid Fetcher Architecture
YouTube blocks transcript requests from cloud IPs. The solution:

1. **Local Fetcher** (`local_fetcher.py` + `Dockerfile.fetcher`): Runs on a home server via Docker, fetches transcripts using residential IP
2. **Lambda**: Receives pre-fetched transcripts via `run_agent_with_transcript()`, handles AI processing
3. **Deployment**: GitHub Actions deploys fetcher to home server via Tailscale SSH (see `.github/workflows/deploy.yml`)

The `process_transcript: true` flag in Lambda events indicates a pre-fetched transcript from the local fetcher.

**Important**: When `run_agent_with_transcript()` is called, the `get_transcript` tool is filtered out of the available tools list. This prevents the LLM from attempting to re-fetch the transcript (which would fail due to IP blocking). Prompt instructions alone were unreliable—removing the tool entirely is the robust solution.

### Lambda Event Formats
The Lambda handler accepts multiple formats:
```python
# Direct video
{"video_url": "https://youtube.com/watch?v=VIDEO_ID"}

# Single channel
{"channel_url": "https://youtube.com/@ChannelName"}

# Batch channels (scheduled runs)
{"channel_urls": ["https://youtube.com/@Ch1", "https://youtube.com/@Ch2"]}

# Pre-fetched transcript from local fetcher
{"process_transcript": true, "video_url": "...", "video_id": "...", "transcript": "..."}
```

### Observability (Dual: Langfuse + ADOT)
Two complementary observability layers:

**Langfuse** (LLM-level observability):
- `@observe()` decorators on `run_agent()`, `_llm_call()`, `handle_tool_call()` in `agent.py`
- `@observe()` decorators on `chat()`, `retrieve_from_knowledge_base()`, `_converse()` in `chatbot.py`
- Tracks prompts, completions, token usage, cost, tool calls in a conversation-level UI
- Configured via `LANGFUSE_HOST`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` env vars
- Self-hosted Langfuse v3 on EC2 (t3.medium) running Docker Compose with 6 services: web, worker, PostgreSQL, Redis, ClickHouse, MinIO (conditional on `var.enable_langfuse`)
- Auto-init creates org/project/API keys on first boot; Terraform generates API keys and injects them into Lambda + chatbot env vars
- Shares the chatbot ALB via host-based routing (`langfuse.*` host header)
- Connect via SSM Session Manager: `aws ssm start-session --target <instance-id>`

**ADOT/X-Ray** (infrastructure-level tracing):
- Auto-instrumented via `opentelemetry-instrument` entrypoint in Lambda/ECS Dockerfiles
- Traces HTTP latency, cold starts, Bedrock API errors
- Controlled by `var.enable_observability` in Terraform

**`observability.py`** provides shared utilities:
- `sanitize_log_value()` / `sanitize_log_dict()` — log injection prevention
- `get_logger()` — structured logging (stdout captured by ECS awslogs / Lambda)
- `flush_traces()` — ADOT trace flush for Lambda cold shutdown

### Adding New Tools
1. Create `tools/my_tool.py` with:
   - `TOOL_DEFINITION` dict (JSON schema for Claude API)
   - Main function implementation
2. Export in `tools/__init__.py`: add to `ALL_TOOLS` list
3. Add dispatch case in `handle_tool_call()` in `agent.py`

### Bedrock Knowledge Base (Semantic Search)
When `enable_knowledge_base = true`, notes are indexed for semantic search:

- **S3 Vectors**: Vector storage using `amazon.titan-embed-text-v2:0` embeddings (1024 dimensions, cosine similarity)
- **Knowledge Base**: Bedrock Knowledge Base connected to S3 Vectors index
- **Auto-sync**: Lambda trigger on `s3:ObjectCreated:*` for `notes/*.md` starts ingestion automatically
- **Metadata fix**: Large Bedrock metadata moved to non-filterable storage (40KB limit) to avoid 2KB filterable limit errors

**Query the Knowledge Base:**
```bash
aws bedrock-agent-runtime retrieve \
  --knowledge-base-id <KB_ID> \
  --retrieval-query '{"text": "your search query"}' \
  --region us-east-1
```

### RAG Chatbot
A standalone chatbot that queries the Bedrock Knowledge Base of video summaries. Runs as a separate server — no dependency on `agent.py` or `ANTHROPIC_API_KEY`.

**Architecture**: Retrieve + Converse pattern (two separate boto3 calls):
1. `chatbot.py` — Core logic: `retrieve_from_knowledge_base()` calls `bedrock-agent-runtime.retrieve()`, then `chat()`/`chat_stream()` calls `bedrock-runtime.converse()`/`converse_stream()`
2. `chatbot_server.py` — Standalone FastAPI server (port 8081) with `/api/chat` and `/api/chat/stream` SSE endpoints
3. `frontend/` — React (Vite) chat UI with SSE streaming and source citations

**Bedrock Guardrails**: Content filtering via `terraform/bedrock_guardrail.tf` — blocks hate/insults/sexual/violence/misconduct/prompt attacks (all HIGH), off-topic questions, and profanity.

**Key details**:
- Converse API `content` is a list of blocks: `[{"text": "..."}]`, not a plain string
- `PROMPT_ATTACK` filter: output strength MUST be `NONE` (AWS requirement)
- Guardrail version in Converse API must be numeric (e.g., `"1"`), not `"DRAFT"`
- Cross-region model ID format: `us.anthropic.claude-sonnet-4-5-20250929-v1:0` (includes date, uses `:0` suffix); IAM needs both `arn:aws:bedrock:*::foundation-model/anthropic.*` and inference-profile ARN
- Frontend dev: `cd frontend && npm run dev` (port 5173) proxies `/api/*` to `http://localhost:8081`

**Docker**: `docker-compose up chatbot` runs standalone on port 8081.

**Deployment**: ECS Fargate behind ALB (HTTP only; Cloudflare CNAME + proxy handles HTTPS). Public subnets with `assign_public_ip = true` (no NAT Gateway). CI/CD updates task definition with new image SHA via `aws ecs register-task-definition` + `update-service`.

### Key Implementation Notes
- **YouTube Transcript API v1.2.3+**: Uses instance-based API: `YouTubeTranscriptApi().fetch(video_id)`
- **Video metadata**: Fetched via YouTube oembed API (no API key needed)
- **Slack**: Uses Block Kit formatting, not markdown
- **Notes backend**: Configurable via `NOTES_BACKEND` env var (`local` or `s3`)
- **Processed video tracking**: `notes/processed_videos.json` in S3 prevents duplicate processing

## Entry Points

| Entry Point | Use Case |
|-------------|----------|
| `agent.py` | CLI - direct execution with video URL or channel URL |
| `lambda_handler.py` | AWS Lambda handler (supports video, channel, batch) |
| `server.py` | FastAPI HTTP server with `/analyze` endpoint |
| `chatbot_server.py` | Standalone FastAPI chatbot server (port 8081) |
| `local_fetcher.py` | Cron-based fetcher for home server deployment |
| `run_local.py` | Interactive REPL loop for testing multiple URLs |
| `run_scheduled.py` | Scheduled channel monitoring (reads `MONITOR_CHANNEL_URLS`) |

## Terraform Infrastructure

Located in `terraform/`:
- `main.tf` / `backend.tf` / `variables.tf` / `outputs.tf` - Provider config, state backend, variables
- `lambda.tf` - Lambda function with OTEL environment variables
- `iam.tf` - IAM roles for Lambda, S3, X-Ray, CloudWatch
- `ecr.tf` - ECR repository for Lambda container image
- `cloudwatch.tf` - Log groups and Transaction Search resource policy
- `s3.tf` - Notes storage bucket
- `bedrock_kb.tf` - S3 Vectors bucket/index, Bedrock Knowledge Base, data source
- `bedrock_kb_sync.tf` - Auto-sync Lambda triggered by S3 events
- `bedrock_guardrail.tf` - Bedrock Guardrail for chatbot content filtering
- `ecs_chatbot.tf` - ECS Fargate chatbot: ECR, ALB, security groups, ECS cluster/service/task def, IAM roles
- `langfuse.tf` - Langfuse v3 LLM observability: EC2 Docker Compose (6 services), ALB host-based routing, auto-init API keys

Key variables:
- `enable_observability` - Controls ADOT/X-Ray infra tracing setup
- `enable_knowledge_base` - Controls Bedrock Knowledge Base, S3 Vectors, and ECS chatbot deployment
- `enable_langfuse` - Controls Langfuse v3 EC2 Docker Compose deployment

## Environment Variables

Required:
- `ANTHROPIC_API_KEY`

Optional:
- `SLACK_WEBHOOK_URL` - Slack webhook for notifications
- `NOTES_BACKEND` - `local` (default) or `s3`
- `NOTES_LOCAL_DIR` - Directory for local notes (default: `./notes`)
- `NOTES_S3_BUCKET` - S3 bucket for cloud storage
- `CLAUDE_MODEL` - Model ID (default: `claude-sonnet-4-20250514`)
- `MONITOR_CHANNEL_URLS` - Comma-separated channel URLs for scheduled monitoring
- `LANGFUSE_HOST` - Langfuse server URL for LLM observability
- `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` - Langfuse API keys
- `KNOWLEDGE_BASE_ID` - Bedrock Knowledge Base ID for RAG chatbot
- `CHATBOT_MODEL_ID` - Bedrock model for chatbot (default: `us.anthropic.claude-sonnet-4-5-20250929-v1:0`)
- `BEDROCK_GUARDRAIL_ID` / `BEDROCK_GUARDRAIL_VERSION` - Bedrock Guardrail config
- `KB_MAX_RESULTS` - Max KB retrieval results per query (default: `5`)
