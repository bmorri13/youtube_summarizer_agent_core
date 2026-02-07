"""RAG Chatbot - Query YouTube video summaries via Bedrock Knowledge Base.

Uses Retrieve + Converse pattern (two separate boto3 calls) for full control
over system prompt, guardrails, streaming, and observability.
"""

import json
import os
import uuid

import boto3
from langfuse import observe, get_client

from observability import (
    sanitize_log_value,
    get_logger,
)

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


@observe(as_type="retriever", name="kb_retrieve")
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

    get_client().update_current_span(
        metadata={"kb_id": kb_id, "max_results": max_results, "result_count": len(results)},
    )

    return results


def _build_converse_params(system_prompt: str, messages: list, stream: bool = False):
    """Build parameters for Converse/ConverseStream API call."""
    params = {
        "modelId": CHATBOT_MODEL_ID,
        "system": [{"text": system_prompt}],
        "messages": messages,
        "inferenceConfig": {
            "maxTokens": 2048,
            "temperature": 0.3,
        },
    }

    if GUARDRAIL_ID and GUARDRAIL_VERSION:
        params["guardrailConfig"] = {
            "guardrailIdentifier": GUARDRAIL_ID,
            "guardrailVersion": GUARDRAIL_VERSION,
        }
        if stream:
            params["guardrailConfig"]["streamProcessingMode"] = "async"

    return params


@observe()
def chat(messages: list, session_id: str = None):
    """Non-streaming chat with RAG retrieval."""
    logger = get_logger()
    session_id = session_id or str(uuid.uuid4())

    get_client().update_current_trace(session_id=session_id)

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

    # Build context from retrieved results
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
    system_prompt = SYSTEM_PROMPT.format(context=context)

    # Convert messages to Bedrock Converse format
    converse_messages = []
    for msg in messages:
        converse_messages.append({
            "role": msg["role"],
            "content": [{"text": msg["content"]}],
        })

    # Call Converse API
    response = _converse(system_prompt, converse_messages)

    # Extract response
    output = response.get("output", {})
    message = output.get("message", {})
    response_text = ""
    for block in message.get("content", []):
        if "text" in block:
            response_text += block["text"]

    # Check for guardrail intervention
    stop_reason = response.get("stopReason", "")
    if stop_reason == "guardrail_intervened":
        logger.warning(f"Guardrail intervened for session {session_id}")

    # Extract usage for response
    usage_data = response.get("usage", {})
    usage = {
        "input_tokens": usage_data.get("inputTokens", 0),
        "output_tokens": usage_data.get("outputTokens", 0),
    }

    return {
        "response": response_text,
        "sources": sources,
        "usage": usage,
        "session_id": session_id,
    }


@observe(as_type="generation", name="bedrock_converse")
def _converse(system_prompt: str, converse_messages: list):
    """Call Bedrock Converse API, tracked as a Langfuse generation."""
    client = _get_runtime_client()
    params = _build_converse_params(system_prompt, converse_messages)
    response = client.converse(**params)

    usage_data = response.get("usage", {})
    get_client().update_current_generation(
        model=CHATBOT_MODEL_ID,
        usage_details={
            "input_tokens": usage_data.get("inputTokens", 0),
            "output_tokens": usage_data.get("outputTokens", 0),
        },
        metadata={"stop_reason": response.get("stopReason", "")},
    )

    return response


def chat_stream(messages: list, session_id: str = None):
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

    # Build context and sources
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
    system_prompt = SYSTEM_PROMPT.format(context=context)

    # Send sources early
    yield f"data: {json.dumps({'type': 'sources', 'sources': sources})}\n\n"

    # Convert messages to Bedrock Converse format
    converse_messages = []
    for msg in messages:
        converse_messages.append({
            "role": msg["role"],
            "content": [{"text": msg["content"]}],
        })

    # Call ConverseStream API
    client = _get_runtime_client()
    params = _build_converse_params(system_prompt, converse_messages, stream=True)
    response = client.converse_stream(**params)

    total_input_tokens = 0
    total_output_tokens = 0
    guardrail_intervened = False

    for event in response.get("stream", []):
        if "contentBlockDelta" in event:
            delta = event["contentBlockDelta"].get("delta", {})
            if "text" in delta:
                yield f"data: {json.dumps({'type': 'chunk', 'content': delta['text']})}\n\n"

        elif "metadata" in event:
            usage_data = event["metadata"].get("usage", {})
            total_input_tokens = usage_data.get("inputTokens", 0)
            total_output_tokens = usage_data.get("outputTokens", 0)

        elif "guardrailAction" in event:
            guardrail_intervened = True

    if guardrail_intervened:
        logger.warning(f"Guardrail intervened (streaming) for session {session_id}")

    yield f"data: {json.dumps({'type': 'done', 'session_id': session_id, 'usage': {'input_tokens': total_input_tokens, 'output_tokens': total_output_tokens}})}\n\n"
