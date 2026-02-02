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

# Docker services
docker-compose up local     # Interactive local dev
docker-compose up server    # HTTP server (port 8080)
docker-compose up lambda    # Lambda emulation (port 9000)

# Test Lambda locally
curl -X POST "http://localhost:9000/2015-03-31/functions/function/invocations" \
  -d '{"video_url": "https://youtube.com/watch?v=VIDEO_ID"}'

# Terraform deployment
cd terraform && terraform init && terraform apply

# Manually trigger local fetcher (requires Tailscale access to home server)
ssh root@docker-compose-03 "cd /opt/docker/yt-transcript && docker compose run --rm fetcher python local_fetcher.py"
```

## Architecture

### Agent Loop Pattern
The agent in `agent.py` implements a standard Anthropic tool-calling loop:

1. `SYSTEM_PROMPT` defines the agent's behavior and workflow
2. `ALL_TOOLS` (from `tools/__init__.py`) provides tool schemas to Claude
3. `run_agent()` loops until `stop_reason == "end_turn"` or max turns reached
4. `handle_tool_call()` dispatches tool executions and logs results

### Hybrid Fetcher Architecture
YouTube blocks transcript requests from cloud IPs. The solution:

1. **Local Fetcher** (`local_fetcher.py` + `Dockerfile.fetcher`): Runs on a home server via Docker, fetches transcripts using residential IP
2. **Lambda**: Receives pre-fetched transcripts via `run_agent_with_transcript()`, handles AI processing
3. **Deployment**: GitHub Actions deploys fetcher to home server via Tailscale SSH (see `.github/workflows/deploy.yml`)

The `process_transcript: true` flag in Lambda events indicates a pre-fetched transcript from the local fetcher.

**Important**: When `run_agent_with_transcript()` is called, the `get_transcript` tool is filtered out of the available tools list. This prevents the LLM from attempting to re-fetch the transcript (which would fail due to IP blocking). Prompt instructions alone were unreliable—removing the tool entirely is the robust solution.

### Adding New Tools
1. Create `tools/my_tool.py` with:
   - `TOOL_DEFINITION` dict (JSON schema for Claude API)
   - Main function implementation
2. Export in `tools/__init__.py`
3. Add dispatch case in `handle_tool_call()` in `agent.py`

### Key Implementation Notes
- **YouTube Transcript API v1.2.3+**: Uses instance-based API: `YouTubeTranscriptApi().fetch(video_id)`
- **Video metadata**: Fetched via YouTube oembed API (no API key needed)
- **Slack**: Uses Block Kit formatting, not markdown
- **Notes backend**: Configurable via `NOTES_BACKEND` env var (`local` or `s3`)
- **Processed video tracking**: `notes/processed_videos.json` in S3 prevents duplicate processing

## Entry Points

| Entry Point | Use Case |
|-------------|----------|
| `agent.py` | CLI - direct execution with video URL |
| `lambda_handler.py` | AWS Lambda handler (supports video, channel, batch) |
| `server.py` | FastAPI HTTP server with `/analyze` endpoint |
| `local_fetcher.py` | Cron-based fetcher for home server deployment |

## Terraform Infrastructure

Located in `terraform/`:
- `lambda.tf` - Lambda function with OTEL environment variables
- `iam.tf` - IAM roles for Lambda, S3, X-Ray, CloudWatch
- `cloudwatch.tf` - Log groups and Transaction Search resource policy
- `eventbridge.tf` - Scheduled triggers for channel monitoring
- `s3.tf` - Notes storage bucket

Key variable: `enable_observability` controls ADOT/AgentCore tracing setup.

## Environment Variables

Required:
- `ANTHROPIC_API_KEY`

Optional:
- `SLACK_WEBHOOK_URL` - Slack webhook for notifications
- `NOTES_BACKEND` - `local` (default) or `s3`
- `NOTES_LOCAL_DIR` - Directory for local notes (default: `./notes`)
- `NOTES_S3_BUCKET` - S3 bucket for cloud storage
- `CLAUDE_MODEL` - Model ID (default: `claude-sonnet-4-20250514`)
- `AGENT_OBSERVABILITY_ENABLED` - Set `true` for OpenTelemetry tracing + CloudWatch logging
- `MONITOR_CHANNEL_URLS` - Comma-separated channel URLs for scheduled monitoring
