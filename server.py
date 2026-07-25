"""FastAPI HTTP server for YouTube Analyzer Agent."""

import logging
import os
import re
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

load_dotenv()

from agent import run_agent

logger = logging.getLogger(__name__)

# Hosts whose watch URLs we accept. Matched against the parsed hostname, not by
# substring — "evil.com/?x=youtube.com" contains "youtube.com" but is not YouTube.
ALLOWED_YOUTUBE_HOSTS = frozenset({
    "youtube.com", "www.youtube.com", "m.youtube.com",
    "youtu.be", "www.youtu.be",
})

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def is_valid_video_ref(value: str) -> bool:
    """Return True if value is a bare 11-char video ID or a URL on a YouTube host."""
    value = value.strip()

    if VIDEO_ID_RE.match(value):
        return True

    try:
        parsed = urlparse(value)
    except ValueError:
        return False

    if parsed.scheme not in ("http", "https"):
        return False

    return (parsed.hostname or "").lower() in ALLOWED_YOUTUBE_HOSTS


class AnalyzeRequest(BaseModel):
    """Request model for video analysis."""
    video_url: str


class AnalyzeResponse(BaseModel):
    """Response model for video analysis."""
    video_url: str
    result: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    print("YouTube Analyzer Server starting...")
    yield
    print("YouTube Analyzer Server shutting down...")


app = FastAPI(
    title="YouTube Analyzer API",
    description="AI-powered YouTube video analysis using Claude",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/")
async def root():
    """API information endpoint."""
    return {
        "name": "YouTube Analyzer API",
        "version": "1.0.0",
        "endpoints": {
            "GET /": "This information",
            "GET /health": "Health check",
            "POST /analyze": "Analyze a YouTube video"
        },
        "usage": {
            "analyze": {
                "method": "POST",
                "body": {"video_url": "https://www.youtube.com/watch?v=VIDEO_ID"}
            }
        }
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "youtube-analyzer",
        "model": os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6"),
        "slack_configured": bool(
            os.environ.get("SLACK_WEBHOOK_URL") or os.environ.get("SLACK_BOT_TOKEN")
        ),
        "notes_backend": os.environ.get("NOTES_BACKEND", "local")
    }


@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze_video(request: AnalyzeRequest):
    """Analyze a YouTube video.

    Fetches the transcript, generates a summary, saves notes, and sends Slack notification.
    """
    if not request.video_url:
        raise HTTPException(status_code=400, detail="video_url is required")

    if not is_valid_video_ref(request.video_url):
        raise HTTPException(
            status_code=400,
            detail="Invalid video_url. Provide a YouTube URL or 11-character video ID."
        )

    try:
        result = run_agent(request.video_url)
        return AnalyzeResponse(video_url=request.video_url, result=result)

    except Exception:
        logger.exception("Analysis failed for %s", request.video_url)
        raise HTTPException(status_code=500, detail="Analysis failed")


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler.

    Logs server-side and returns a generic message — echoing str(exc) to the
    client leaks internal paths and upstream API error details.
    """
    logger.exception("Unhandled error handling %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error"}
    )


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8080))
    host = os.environ.get("HOST", "0.0.0.0")

    print(f"Starting server on {host}:{port}")
    uvicorn.run(app, host=host, port=port)
