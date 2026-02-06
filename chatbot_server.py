"""FastAPI server for RAG Chatbot - queries YouTube video summaries via Bedrock Knowledge Base.

Standalone server, no dependency on agent.py or Anthropic API key.
Run: python chatbot_server.py (port 8081)
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
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
    kb_configured = bool(os.environ.get("KNOWLEDGE_BASE_ID"))
    guardrail_configured = bool(
        os.environ.get("BEDROCK_GUARDRAIL_ID") and os.environ.get("BEDROCK_GUARDRAIL_VERSION")
    )
    print(f"  Knowledge Base configured: {kb_configured}")
    print(f"  Guardrail configured: {guardrail_configured}")
    if FRONTEND_DIST.exists():
        print(f"  Frontend build found at {FRONTEND_DIST}")
    else:
        print(f"  No frontend build at {FRONTEND_DIST} — /chat will return fallback message")
    yield
    print("Chatbot Server shutting down...")


app = FastAPI(
    title="YouTube Summaries Chatbot",
    description="RAG chatbot for querying YouTube video summaries via Bedrock Knowledge Base",
    version="1.0.0",
    lifespan=lifespan,
)

# Mount static assets if frontend build exists
if FRONTEND_DIST.exists() and (FRONTEND_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="frontend-assets")


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
        "knowledge_base_configured": bool(os.environ.get("KNOWLEDGE_BASE_ID")),
        "guardrail_configured": bool(
            os.environ.get("BEDROCK_GUARDRAIL_ID") and os.environ.get("BEDROCK_GUARDRAIL_VERSION")
        ),
    }


@app.post("/api/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    """Non-streaming chat with RAG retrieval."""
    if not os.environ.get("KNOWLEDGE_BASE_ID"):
        raise HTTPException(status_code=503, detail="Knowledge Base not configured")

    messages = [{"role": m.role, "content": m.content} for m in request.messages]
    result = chat(messages, session_id=request.session_id)
    return ChatResponse(**result)


@app.post("/api/chat/stream")
async def chat_stream_endpoint(request: ChatRequest):
    """Streaming chat with RAG retrieval via SSE."""
    if not os.environ.get("KNOWLEDGE_BASE_ID"):
        raise HTTPException(status_code=503, detail="Knowledge Base not configured")

    messages = [{"role": m.role, "content": m.content} for m in request.messages]

    return StreamingResponse(
        chat_stream(messages, session_id=request.session_id),
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
