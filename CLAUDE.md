# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

YouTube Analyzer Agent - an AI agent that analyzes YouTube videos by fetching transcripts, generating summaries, saving notes, and sending Slack notifications. Uses LangGraph + ChatAnthropic (direct Anthropic API) with LangChain @tool decorators. Runs on a homelab Docker Compose stack with Supabase Cloud for vector search.

## Development Commands

```bash
# Setup
python -m venv venv && source venv/bin/activate && pip install -r requirements.txt

# Run agent locally (loads .env automatically)
python agent.py "https://www.youtube.com/watch?v=VIDEO_ID"

# Run agent on a channel (checks latest video)
python agent.py "https://www.youtube.com/@ChannelName"

# Docker services
docker-compose up local     # Interactive local dev (REPL)
docker-compose up server    # HTTP server (port 8080)
docker-compose up chatbot   # RAG chatbot (port 8081)
docker-compose up fetcher   # Transcript fetcher (cron, for home server)
VIDEO_URL="https://..." docker-compose up analyze  # Single video analysis

# Manually trigger fetcher
docker compose run --rm fetcher python local_fetcher.py

# Ingest existing notes into Supabase vector store
python ingest_notes.py [notes_directory]

# Frontend dev
cd frontend && npm run dev  # port 5173, proxies /api/* to localhost:8081
```

## Testing

There is no automated test suite. Manual testing is done by running the agent against real YouTube URLs.

## Architecture

### Agent Loop Pattern
The agent in `agent.py` uses LangGraph's `create_react_agent` with `ChatAnthropic`:

1. `SYSTEM_PROMPT` defines the agent's behavior and workflow
2. `ALL_TOOLS` (from `tools/__init__.py`) provides LangChain `@tool`-decorated functions
3. `create_react_agent(model, tools)` handles the tool-calling loop automatically

### Tools
Current tools in `tools/` — each uses LangChain `@tool` decorator and returns JSON strings:
- `youtube.py` - `get_transcript`: Fetch video transcript and metadata via `youtube-transcript-api`
- `channel.py` - `get_latest_channel_video`: Get latest video from a channel via RSS feed (filters out Shorts < 90s)
- `notes.py` - `save_note`: Save analysis to local/S3, track processed videos, ingest into vector store
- `slack.py` - `send_slack_notification`: Send Block Kit formatted notifications

Helper functions (exported from `tools/__init__.py` but NOT in `ALL_TOOLS` — used by fetcher, not the LLM):
- `is_video_processed()` - Check if video already processed (prevents duplicates)
- `mark_video_processed()` - Mark video as processed
- `update_channel_checked()` - Track last channel check timestamp

### Fetcher Architecture
YouTube blocks transcript requests from cloud IPs. The fetcher runs on a homelab server with a residential IP.

1. **Local Fetcher** (`local_fetcher.py` + `Dockerfile.fetcher`): Runs on home server via Docker cron, fetches transcripts and runs the agent directly in-process via `run_agent_with_transcript()`
2. **Deployment**: GitHub Actions deploys to home server via Tailscale SSH (see `.github/workflows/deploy.yml`)

**Important**: When `run_agent_with_transcript()` is called, the `get_transcript` tool is filtered out of the available tools list. This prevents the LLM from attempting to re-fetch the transcript. Prompt instructions alone were unreliable—removing the tool entirely is the robust solution.

### Vector Store (Supabase pgvector)
Notes are indexed for semantic search in Supabase Cloud:

- **Embeddings**: OpenAI `text-embedding-3-small` (1536 dimensions)
- **Storage**: Supabase PostgreSQL with pgvector extension
- **Auto-ingest**: `save_note()` tool automatically ingests into vector store when `SUPABASE_URL` is configured
- **Retrieval**: `vector_store.retrieve_similar_documents()` calls Supabase RPC `match_documents`
- **Bulk ingest**: `python ingest_notes.py` for migrating existing notes
- **Schema**: See `supabase_schema.sql` — run in Supabase SQL editor to set up

### RAG Chatbot
A standalone chatbot that queries video summaries via Supabase pgvector.

**Architecture**: Retrieve (Supabase) + ChatAnthropic pattern:
1. `chatbot.py` — Core logic: `retrieve_documents()` calls `vector_store.retrieve_similar_documents()`, then `chat()`/`chat_stream()` uses `ChatAnthropic`
2. `chatbot_server.py` — FastAPI server (port 8081) with `/api/chat` and `/api/chat/stream` SSE endpoints
3. `frontend/` — React (Vite) chat UI with SSE streaming and source citations

**Docker**: `docker-compose up chatbot` runs on port 8081.

**External access**: Cloudflare Tunnel via `cloudflared` service in Docker Compose. Configure in Cloudflare dashboard: `chatbot.yourdomain.com` → `http://chatbot:8081`

### Adding New Tools
1. Create `tools/my_tool.py` with:
   - A function decorated with `@tool` from `langchain_core.tools`
   - Function must return a JSON string (`json.dumps(result)`)
   - Docstring becomes the tool description for the LLM
2. Export in `tools/__init__.py`: add the tool function to `ALL_TOOLS` list
3. No dispatch code needed — LangGraph auto-dispatches to `@tool` functions

### Key Implementation Notes
- **LLM via Anthropic API**: Agent uses `ChatAnthropic` (LangChain) with direct Anthropic API key
- **YouTube Transcript API v1.2.3+**: Uses instance-based API: `YouTubeTranscriptApi().fetch(video_id)`
- **Video metadata**: Fetched via YouTube oembed API (no API key needed)
- **Slack**: Uses Block Kit formatting, not markdown
- **Notes backend**: Configurable via `NOTES_BACKEND` env var (`local` or `s3`)
- **Processed video tracking**: `processed_videos.json` in notes directory prevents duplicate processing
- **Observability**: Stdout logging only via `observability.py`'s `get_logger()`

## Entry Points

| Entry Point | Use Case |
|-------------|----------|
| `agent.py` | CLI - direct execution with video URL or channel URL |
| `server.py` | FastAPI HTTP server with `/analyze` endpoint |
| `chatbot_server.py` | FastAPI chatbot server (port 8081) |
| `local_fetcher.py` | Cron-based fetcher for home server deployment |
| `run_local.py` | Interactive REPL loop for testing multiple URLs |
| `run_scheduled.py` | Scheduled channel monitoring (reads `MONITOR_CHANNEL_URLS`) |
| `ingest_notes.py` | Bulk ingest notes into Supabase vector store |
| `lambda_handler.py` | AWS Lambda handler (legacy, kept for reference) |

## CI/CD

Single GitHub Actions workflow in `.github/workflows/`:
- **`deploy.yml`** — Deploys to homelab via Tailscale SSH: syncs code via rsync, rebuilds Docker containers. Triggered on push to main.

## Environment Variables

Required:
- `ANTHROPIC_API_KEY` - Anthropic API key for LLM (agent + chatbot)

Required for chatbot:
- `SUPABASE_URL` - Supabase project URL
- `SUPABASE_SERVICE_KEY` - Supabase service role key
- `OPENAI_API_KEY` - OpenAI API key for embeddings

Optional:
- `SLACK_WEBHOOK_URL` - Slack webhook for notifications
- `NOTES_BACKEND` - `local` (default) or `s3`
- `NOTES_LOCAL_DIR` - Directory for local notes (default: `./notes`)
- `CLAUDE_MODEL` - Anthropic model ID (default: `claude-sonnet-4-6`)
- `CHATBOT_MODEL_ID` - Anthropic model for chatbot (default: `claude-sonnet-4-6`)
- `MONITOR_CHANNEL_URLS` - Comma-separated channel URLs for scheduled monitoring
- `KB_MAX_RESULTS` - Max retrieval results per query (default: `5`)
- `EMBEDDING_MODEL` - OpenAI embedding model (default: `text-embedding-3-small`)
- `CLOUDFLARE_TUNNEL_TOKEN` - Cloudflare Tunnel token for external access
- `LOG_LEVEL` - Logging level (default: `INFO`)

## Terraform Infrastructure (Legacy)

The `terraform/` directory contains the previous AWS infrastructure (Lambda, ECS, Bedrock KB, Langfuse EC2, etc.). Kept for reference and potential rollback. The project now runs on a homelab Docker Compose stack.
