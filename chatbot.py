"""RAG Chatbot - Query YouTube video summaries via Supabase pgvector.

Uses vector_store for retrieval + ChatAnthropic for generation.
"""

import json
import os
import uuid

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from observability import sanitize_log_value, get_logger

# Configuration
CHATBOT_MODEL_ID = os.environ.get("CHATBOT_MODEL_ID", "claude-sonnet-4-6")
KB_MAX_RESULTS = int(os.environ.get("KB_MAX_RESULTS", "5"))

SYSTEM_PROMPT = """You are a helpful assistant that answers questions about YouTube videos that have been analyzed and summarized.

You ONLY answer based on the retrieved context provided below. If the context does not contain relevant information to answer the question, respond with: "I don't have information about that in my video summaries."

Do NOT make up information or use knowledge outside of the provided context. Always cite which video(s) your answer comes from when possible.

Retrieved context:
{context}"""

def _create_chatbot_model():
    """Create ChatAnthropic model."""
    return ChatAnthropic(model=CHATBOT_MODEL_ID, max_tokens=2048, temperature=0.3)


def retrieve_documents(query: str, max_results: int = None):
    """Retrieve relevant documents from Supabase pgvector."""
    logger = get_logger()
    max_results = max_results or KB_MAX_RESULTS

    try:
        from vector_store import retrieve_similar_documents
        results = retrieve_similar_documents(query, max_results=max_results)
        logger.info(f"Vector retrieve: {len(results)} results for query: {sanitize_log_value(query, 100)}")
        return results
    except Exception as e:
        logger.error(f"Vector retrieval failed: {e}")
        return []


def _extract_text(content):
    """Extract text from LangChain message content (string or list of content blocks)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    return str(content)


def _build_context_and_sources(kb_results: list):
    """Build context string and sources list from KB results."""
    context_parts = []
    sources = []
    for i, result in enumerate(kb_results):
        context_parts.append(f"[Source {i + 1}] (score: {result['score']:.2f})\n{result['text']}")
        if result["source_uri"]:
            sources.append({
                "source_uri": result["source_uri"],
                "score": result["score"],
            })

    context = "\n\n---\n\n".join(context_parts) if context_parts else "No relevant context found."
    return context, sources


def _convert_to_langchain_messages(system_prompt: str, messages: list):
    """Convert chat messages to LangChain message format."""
    lc_messages = [SystemMessage(content=system_prompt)]
    for msg in messages:
        if msg["role"] == "user":
            lc_messages.append(HumanMessage(content=msg["content"]))
        else:
            lc_messages.append(AIMessage(content=msg["content"]))
    return lc_messages


def chat(messages: list, session_id: str = None, user_id: str = None):
    """Non-streaming chat with RAG retrieval."""
    logger = get_logger()
    session_id = session_id or str(uuid.uuid4())

    # Extract latest user message for retrieval
    user_query = ""
    for msg in reversed(messages):
        if msg["role"] == "user":
            user_query = msg["content"]
            break

    if not user_query:
        return {
            "response": "Please provide a question.",
            "sources": [],
            "usage": {},
            "session_id": session_id,
        }

    # Retrieve from vector store
    results = retrieve_documents(user_query)
    context, sources = _build_context_and_sources(results)
    system_prompt = SYSTEM_PROMPT.format(context=context)

    # Build LangChain messages
    lc_messages = _convert_to_langchain_messages(system_prompt, messages)

    # Create model and invoke
    model = _create_chatbot_model()
    response = model.invoke(lc_messages)

    usage = response.usage_metadata or {}
    response_text = _extract_text(response.content)

    return {
        "response": response_text,
        "sources": sources,
        "usage": {
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
        },
        "session_id": session_id,
    }


def chat_stream(messages: list, session_id: str = None, user_id: str = None):
    """Streaming chat with RAG retrieval. Yields SSE-formatted JSON strings."""
    logger = get_logger()
    session_id = session_id or str(uuid.uuid4())

    # Extract latest user message for retrieval
    user_query = ""
    for msg in reversed(messages):
        if msg["role"] == "user":
            user_query = msg["content"]
            break

    if not user_query:
        yield f"data: {json.dumps({'type': 'chunk', 'content': 'Please provide a question.'})}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'session_id': session_id})}\n\n"
        return

    # Retrieve from vector store
    results = retrieve_documents(user_query)
    context, sources = _build_context_and_sources(results)
    system_prompt = SYSTEM_PROMPT.format(context=context)

    # Send sources early
    yield f"data: {json.dumps({'type': 'sources', 'sources': sources})}\n\n"

    # Build LangChain messages
    lc_messages = _convert_to_langchain_messages(system_prompt, messages)

    # Create model and stream
    model = _create_chatbot_model()

    for chunk in model.stream(lc_messages):
        text = _extract_text(chunk.content)
        if text:
            yield f"data: {json.dumps({'type': 'chunk', 'content': text})}\n\n"

    yield f"data: {json.dumps({'type': 'done', 'session_id': session_id})}\n\n"
