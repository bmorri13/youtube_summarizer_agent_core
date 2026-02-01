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

# Or with explicit env vars
export $(cat .env | xargs) && python agent.py "URL"

# Docker services
docker-compose up local     # Interactive local dev
docker-compose up server    # HTTP server (port 8080)
docker-compose up lambda    # Lambda emulation (port 9000)
VIDEO_URL="URL" docker-compose up analyze  # Single video analysis

# Test Lambda locally
curl -X POST "http://localhost:9000/2015-03-31/functions/function/invocations" \
  -d '{"video_url": "https://youtube.com/watch?v=VIDEO_ID"}'

# Deploy to Lambda
python deploy_lambda.py --create-api
```

## Architecture

### Agent Loop Pattern
The agent in `agent.py` implements a standard Anthropic tool-calling loop:

1. `SYSTEM_PROMPT` defines the agent's behavior and workflow
2. `ALL_TOOLS` (from `tools/__init__.py`) provides tool schemas to Claude
3. `run_agent()` loops until `stop_reason == "end_turn"` or max turns reached
4. `handle_tool_call()` dispatches tool executions and logs results

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

## Entry Points

| Entry Point | Use Case |
|-------------|----------|
| `agent.py` | CLI - direct execution with video URL |
| `lambda_handler.py` | AWS Lambda handler |
| `server.py` | FastAPI HTTP server with `/analyze` endpoint |
| `run_local.py` | Interactive CLI for local development |

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
