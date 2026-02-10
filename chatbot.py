"""RAG Chatbot - Query YouTube video summaries via Bedrock Knowledge Base.

Uses Retrieve (direct boto3) + ChatBedrockConverse for full control
over system prompt, guardrails, streaming, and observability.
"""

import json
import os
import uuid

import boto3
from langchain_aws import ChatBedrockConverse
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langfuse.langchain import CallbackHandler as LangfuseCallbackHandler

from observability import sanitize_log_value, get_logger

# Configuration
KNOWLEDGE_BASE_ID = os.environ.get("KNOWLEDGE_BASE_ID", "")
CHATBOT_MODEL_ID = os.environ.get("CHATBOT_MODEL_ID", "us.anthropic.claude-sonnet-4-5-20250929-v1:0")
GUARDRAIL_ID = os.environ.get("BEDROCK_GUARDRAIL_ID", "")
GUARDRAIL_VERSION = os.environ.get("BEDROCK_GUARDRAIL_VERSION", "")
KB_MAX_RESULTS = int(os.environ.get("KB_MAX_RESULTS", "5"))
AWS_REGION = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))

SYSTEM_PROMPT = """You are a helpful assistant that answers questions about YouTube videos that have been analyzed and summarized.

You ONLY answer based on the retrieved context provided below. If the context does not contain relevant information to answer the question, respond with: "I don't have information about that in my video summaries."

Do NOT make up information or use knowledge outside of the provided context. Always cite which video(s) your answer comes from when possible.

Retrieved context:
{context}"""

# Lazy-initialized clients
_bedrock_agent_client = None
_bedrock_runtime_client = None


def _get_agent_client():
    global _bedrock_agent_client
    if _bedrock_agent_client is None:
        _bedrock_agent_client = boto3.client("bedrock-agent-runtime", region_name=AWS_REGION)
    return _bedrock_agent_client


def _get_runtime_client():
    global _bedrock_runtime_client
    if _bedrock_runtime_client is None:
        _bedrock_runtime_client = boto3.client("bedrock-runtime", region_name=AWS_REGION)
    return _bedrock_runtime_client


def _create_chatbot_model():
    """Create ChatBedrockConverse with optional guardrails."""
    kwargs = {
        "client": _get_runtime_client(),
        "model_id": CHATBOT_MODEL_ID,
        "max_tokens": 2048,
        "temperature": 0.3,
    }
    if GUARDRAIL_ID and GUARDRAIL_VERSION:
        kwargs["guardrail_config"] = {
            "guardrailIdentifier": GUARDRAIL_ID,
            "guardrailVersion": GUARDRAIL_VERSION,
            "trace": "enabled",
        }
        kwargs["guard_last_turn_only"] = True  # Multi-turn optimization
    return ChatBedrockConverse(**kwargs)


def retrieve_from_knowledge_base(query: str, kb_id: str = None, max_results: int = None):
    """Retrieve relevant documents from Bedrock Knowledge Base."""
    logger = get_logger()
    kb_id = kb_id or KNOWLEDGE_BASE_ID
    max_results = max_results or KB_MAX_RESULTS

    if not kb_id:
        logger.warning("KNOWLEDGE_BASE_ID not configured")
        return []

    client = _get_agent_client()

    response = client.retrieve(
        knowledgeBaseId=kb_id,
        retrievalQuery={"text": query},
        retrievalConfiguration={
            "vectorSearchConfiguration": {
                "numberOfResults": max_results,
            }
        },
    )

    results = []
    for result in response.get("retrievalResults", []):
        text = result.get("content", {}).get("text", "")
        score = result.get("score", 0.0)
        source_uri = result.get("location", {}).get("s3Location", {}).get("uri", "")

        results.append({
            "text": text,
            "score": score,
            "source_uri": source_uri,
        })

    logger.info(f"KB retrieve: {len(results)} results for query: {sanitize_log_value(query, 100)}")
    return results


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

    # Retrieve from KB
    kb_results = retrieve_from_knowledge_base(user_query)
    context, sources = _build_context_and_sources(kb_results)
    system_prompt = SYSTEM_PROMPT.format(context=context)

    # Build LangChain messages
    lc_messages = _convert_to_langchain_messages(system_prompt, messages)

    # Create model and handler
    model = _create_chatbot_model()
    handler = LangfuseCallbackHandler()
    config = {
        "callbacks": [handler],
        "metadata": {
            "langfuse_session_id": session_id,
            "langfuse_user_id": user_id,
            "langfuse_tags": ["chatbot"],
        },
    }

    response = model.invoke(lc_messages, config=config)

    # Check for guardrail intervention
    stop_reason = response.response_metadata.get("stopReason", "")
    if stop_reason == "guardrail_intervened":
        logger.warning(f"Guardrail intervened for session {session_id}")

    usage = response.usage_metadata or {}

    return {
        "response": _extract_text(response.content),
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

    # Retrieve from KB
    kb_results = retrieve_from_knowledge_base(user_query)
    context, sources = _build_context_and_sources(kb_results)
    system_prompt = SYSTEM_PROMPT.format(context=context)

    # Send sources early
    yield f"data: {json.dumps({'type': 'sources', 'sources': sources})}\n\n"

    # Build LangChain messages
    lc_messages = _convert_to_langchain_messages(system_prompt, messages)

    # Create model and handler
    model = _create_chatbot_model()
    handler = LangfuseCallbackHandler()
    config = {
        "callbacks": [handler],
        "metadata": {
            "langfuse_session_id": session_id,
            "langfuse_user_id": user_id,
            "langfuse_tags": ["chatbot", "streaming"],
        },
    }

    full_response = []
    for chunk in model.stream(lc_messages, config=config):
        text = _extract_text(chunk.content)
        if text:
            full_response.append(text)
            yield f"data: {json.dumps({'type': 'chunk', 'content': text})}\n\n"

    yield f"data: {json.dumps({'type': 'done', 'session_id': session_id})}\n\n"
