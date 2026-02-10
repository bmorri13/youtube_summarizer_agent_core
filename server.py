"""FastAPI HTTP server for YouTube Analyzer Agent."""

import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

load_dotenv()

from agent import run_agent


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
        "bedrock_model": os.environ.get("CLAUDE_MODEL", "us.anthropic.claude-sonnet-4-5-20250929-v1:0"),
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

    # Validate it looks like a YouTube URL or video ID
    if not any(domain in request.video_url for domain in ["youtube.com", "youtu.be"]):
        if len(request.video_url) != 11:
            raise HTTPException(
                status_code=400,
                detail="Invalid video_url. Provide a YouTube URL or 11-character video ID."
            )

    try:
        result = run_agent(request.video_url)
        return AnalyzeResponse(video_url=request.video_url, result=result)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler."""
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc)}
    )


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8080))
    host = os.environ.get("HOST", "0.0.0.0")

    print(f"Starting server on {host}:{port}")
    uvicorn.run(app, host=host, port=port)
