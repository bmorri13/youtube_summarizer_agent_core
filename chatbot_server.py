"""FastAPI server for RAG Chatbot - queries YouTube video summaries via Supabase pgvector.

Standalone server.
Run: python chatbot_server.py (port 8081)
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

from chatbot import chat, chat_stream


# --- Pydantic Models ---

class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    session_id: Optional[str] = None


class ChatSource(BaseModel):
    source_uri: str
    score: float


class ChatResponse(BaseModel):
    response: str
    sources: list[ChatSource]
    usage: dict
    session_id: str


# --- App Setup ---

FRONTEND_DIST = Path(__file__).parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    print("Chatbot Server starting...")
    vector_store_configured = bool(os.environ.get("SUPABASE_URL"))
    print(f"  Vector store configured: {vector_store_configured}")
    if FRONTEND_DIST.exists():
        print(f"  Frontend build found at {FRONTEND_DIST}")
    else:
        print(f"  No frontend build at {FRONTEND_DIST} — /chat will return fallback message")
    yield
    print("Chatbot Server shutting down...")


app = FastAPI(
    title="YouTube Summaries Chatbot",
    description="RAG chatbot for querying YouTube video summaries",
    version="1.0.0",
    lifespan=lifespan,
)

# Mount static assets if frontend build exists
if FRONTEND_DIST.exists() and (FRONTEND_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="frontend-assets")


def _extract_user_id(request: Request) -> str | None:
    """Extract user identity from Cloudflare Access header."""
    return request.headers.get("Cf-Access-Authenticated-User-Email")


# --- Endpoints ---

@app.get("/")
async def root():
    """Redirect to chat UI."""
    index_path = FRONTEND_DIST / "index.html"
    if index_path.exists():
        return HTMLResponse(content=index_path.read_text())
    return {
        "name": "YouTube Summaries Chatbot",
        "version": "1.0.0",
        "endpoints": {
            "GET /": "Chat UI (or this info if not built)",
            "GET /health": "Health check",
            "POST /api/chat": "Chat (non-streaming)",
            "POST /api/chat/stream": "Chat (streaming SSE)",
        },
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "youtube-summaries-chatbot",
        "vector_store_configured": bool(os.environ.get("SUPABASE_URL")),
    }


@app.post("/api/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest, raw_request: Request):
    """Non-streaming chat with RAG retrieval."""
    if not os.environ.get("SUPABASE_URL"):
        raise HTTPException(status_code=503, detail="Vector store not configured (SUPABASE_URL)")

    messages = [{"role": m.role, "content": m.content} for m in request.messages]
    user_id = _extract_user_id(raw_request)

    result = chat(messages, session_id=request.session_id, user_id=user_id)
    return ChatResponse(**result)


@app.post("/api/chat/stream")
async def chat_stream_endpoint(request: ChatRequest, raw_request: Request):
    """Streaming chat with RAG retrieval via SSE."""
    if not os.environ.get("SUPABASE_URL"):
        raise HTTPException(status_code=503, detail="Vector store not configured (SUPABASE_URL)")

    messages = [{"role": m.role, "content": m.content} for m in request.messages]
    user_id = _extract_user_id(raw_request)

    return StreamingResponse(
        chat_stream(messages, session_id=request.session_id, user_id=user_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler."""
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc)}
    )


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("CHATBOT_PORT", 8081))
    host = os.environ.get("HOST", "0.0.0.0")

    print(f"Starting chatbot server on {host}:{port}")
    uvicorn.run(app, host=host, port=port)
