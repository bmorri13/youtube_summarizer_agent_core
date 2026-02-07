"""AWS Bedrock AgentCore Observability - Tracing and Logging.

This module provides observability features for the YouTube Analyzer Agent,
using AWS ADOT auto-instrumentation for trace export.

Features:
- ADOT auto-instrumented tracing (via opentelemetry-instrument entrypoint)
- gen_ai.* semantic conventions for LLM tracing
- Custom span helpers for agent-specific tracing
- Structured JSON logging (stdout captured by ECS awslogs / Lambda)
- Log injection prevention via input sanitization
"""

import os
import logging
import json
import re
from datetime import datetime
from functools import wraps
from typing import Callable, Optional, Any
from contextlib import contextmanager

# OpenTelemetry imports
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode


# Configuration
SERVICE_NAME = os.environ.get("OTEL_SERVICE_NAME", "youtube-analyzer-agent")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
OBSERVABILITY_ENABLED = os.environ.get("AGENT_OBSERVABILITY_ENABLED", "").lower() == "true"

# Global state
_logger = None
_tracer_initialized = False


def sanitize_log_value(value: Any, max_length: int = 1000) -> str:
    """Sanitize a value for safe logging to prevent log injection attacks.

    This function:
    - Converts value to string
    - Removes/escapes control characters (newlines, carriage returns, tabs)
    - Truncates overly long strings
    - Escapes characters that could forge log entries

    Args:
        value: The value to sanitize
        max_length: Maximum length of the output string

    Returns:
        A sanitized string safe for logging
    """
    if value is None:
        return "null"

    # Convert to string
    str_value = str(value)

    # Remove or escape control characters that could forge log entries
    # Replace newlines and carriage returns with escaped versions
    str_value = str_value.replace('\r\n', '\\r\\n')
    str_value = str_value.replace('\n', '\\n')
    str_value = str_value.replace('\r', '\\r')
    str_value = str_value.replace('\t', '\\t')

    # Remove other control characters (ASCII 0-31 except those already handled)
    str_value = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', str_value)

    # Truncate if too long
    if len(str_value) > max_length:
        str_value = str_value[:max_length] + "...[truncated]"

    return str_value


def sanitize_log_dict(data: dict, max_length: int = 1000) -> dict:
    """Recursively sanitize all string values in a dictionary for logging.

    Args:
        data: Dictionary to sanitize
        max_length: Maximum length for string values

    Returns:
        A new dictionary with sanitized values
    """
    if not isinstance(data, dict):
        return data

    sanitized = {}
    for key, value in data.items():
        if isinstance(value, str):
            sanitized[key] = sanitize_log_value(value, max_length)
        elif isinstance(value, dict):
            sanitized[key] = sanitize_log_dict(value, max_length)
        elif isinstance(value, list):
            sanitized[key] = [
                sanitize_log_value(item, max_length) if isinstance(item, str)
                else sanitize_log_dict(item, max_length) if isinstance(item, dict)
                else item
                for item in value
            ]
        else:
            sanitized[key] = value
    return sanitized


def _init_tracer():
    """Initialize the OpenTelemetry tracer using AWS ADOT auto-configuration."""
    global _tracer_initialized

    if _tracer_initialized:
        return

    if not OBSERVABILITY_ENABLED:
        print("[Observability] Tracing disabled (AGENT_OBSERVABILITY_ENABLED != true)")
        _tracer_initialized = True
        return

    # When OTEL_PYTHON_DISTRO=aws_distro is set, ADOT handles everything
    if os.environ.get("OTEL_PYTHON_DISTRO") == "aws_distro":
        print("[Observability] Using AWS ADOT auto-configuration for AgentCore")
    else:
        print("[Observability] No ADOT distro configured — traces will be no-ops")

    _tracer_initialized = True


def setup_logging() -> logging.Logger:
    """Initialize logging with console handler (stdout captured by ECS awslogs / Lambda)."""
    global _logger

    if _logger is not None:
        return _logger

    _logger = logging.getLogger("youtube-analyzer")
    _logger.setLevel(getattr(logging, LOG_LEVEL.upper()))

    # Prevent duplicate handlers
    if _logger.handlers:
        return _logger

    # Console handler for local development
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    console_handler.setFormatter(formatter)
    _logger.addHandler(console_handler)

    return _logger


def get_tracer() -> trace.Tracer:
    """Get the tracer, initializing if needed."""
    _init_tracer()
    return trace.get_tracer(__name__, "1.0.0")


def get_logger() -> logging.Logger:
    """Get or create the global logger."""
    global _logger
    if _logger is None:
        _logger = setup_logging()
    return _logger


@contextmanager
def trace_span(name: str, attributes: dict = None):
    """Context manager for creating a traced span.

    Usage:
        with trace_span("fetch_transcript", {"video_id": "abc123"}):
            result = fetch_transcript(video_id)
    """
    tracer = get_tracer()
    logger = get_logger()

    with tracer.start_as_current_span(name) as span:
        if attributes:
            for key, value in attributes.items():
                if value is not None:
                    span.set_attribute(key, str(value))

        # Sanitize attributes to prevent log injection
        safe_attributes = sanitize_log_dict(attributes) if attributes else {}
        logger.info(json.dumps({
            "event": "span_start",
            "span_name": sanitize_log_value(name),
            "attributes": safe_attributes
        }))

        try:
            yield span
            span.set_status(Status(StatusCode.OK))
            logger.info(json.dumps({
                "event": "span_end",
                "span_name": sanitize_log_value(name),
                "status": "OK"
            }))
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            logger.error(json.dumps({
                "event": "span_error",
                "span_name": sanitize_log_value(name),
                "error": sanitize_log_value(str(e))
            }))
            raise


def trace_function(name: str = None, capture_args: bool = False):
    """Decorator to trace a function execution."""
    def decorator(func: Callable) -> Callable:
        span_name = name or func.__name__

        @wraps(func)
        def wrapper(*args, **kwargs):
            attributes = {}
            if capture_args:
                attributes["args_count"] = len(args)
                attributes["kwargs_keys"] = ",".join(kwargs.keys())

            with trace_span(span_name, attributes):
                return func(*args, **kwargs)

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            attributes = {}
            if capture_args:
                attributes["args_count"] = len(args)
                attributes["kwargs_keys"] = ",".join(kwargs.keys())

            with trace_span(span_name, attributes):
                return await func(*args, **kwargs)

        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return wrapper

    return decorator


def log_agent_event(
    event_type: str,
    video_url: str = None,
    video_id: str = None,
    channel_url: str = None,
    is_already_processed: bool = None,
    tool_name: str = None,
    status: str = "success",
    error: str = None,
    metadata: dict = None
):
    """Log a structured agent event to CloudWatch."""
    logger = get_logger()

    event = {
        "event_type": sanitize_log_value(event_type),
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "status": sanitize_log_value(status),
        "service": SERVICE_NAME,
    }

    # Sanitize all user-controlled input to prevent log injection
    if video_url:
        event["video_url"] = sanitize_log_value(video_url)
    if video_id:
        event["video_id"] = sanitize_log_value(video_id)
    if channel_url:
        event["channel_url"] = sanitize_log_value(channel_url)
    if is_already_processed is not None:
        event["is_already_processed"] = is_already_processed
    if tool_name:
        event["tool_name"] = sanitize_log_value(tool_name)
    if error:
        event["error"] = sanitize_log_value(error)
    if metadata:
        event["metadata"] = sanitize_log_dict(metadata)

    # Get current span context if available
    current_span = trace.get_current_span()
    if current_span and current_span.get_span_context().is_valid:
        event["trace_id"] = format(current_span.get_span_context().trace_id, '032x')
        event["span_id"] = format(current_span.get_span_context().span_id, '016x')

    log_message = json.dumps(event)

    if status == "error":
        logger.error(log_message)
    else:
        logger.info(log_message)


def log_tool_call(tool_name: str, tool_input: dict, tool_output: dict):
    """Log a tool invocation with input/output."""
    tracer = get_tracer()

    with tracer.start_as_current_span(f"tool.{tool_name}") as span:
        # Standard attributes
        span.set_attribute("tool.name", tool_name)
        span.set_attribute("tool.input_keys", ",".join(tool_input.keys()))

        success = tool_output.get("success", True)
        span.set_attribute("tool.success", success)

        if not success:
            span.set_status(Status(StatusCode.ERROR, tool_output.get("error", "Unknown error")))

        log_agent_event(
            event_type="tool_call",
            tool_name=tool_name,
            status="success" if success else "error",
            error=tool_output.get("error"),
            metadata={
                "input_keys": list(tool_input.keys()),
                "output_keys": list(tool_output.keys()),
            }
        )


def log_llm_call(
    model: str,
    input_tokens: int = None,
    output_tokens: int = None,
    request_id: str = None
):
    """Log an LLM API call with gen_ai semantic conventions."""
    current_span = trace.get_current_span()

    if current_span and current_span.get_span_context().is_valid:
        # Gen AI semantic conventions (for Bedrock AgentCore)
        current_span.set_attribute("gen_ai.system", "anthropic")
        current_span.set_attribute("gen_ai.request.model", model)

        if input_tokens:
            current_span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
            current_span.set_attribute("gen_ai.usage.prompt_tokens", input_tokens)
        if output_tokens:
            current_span.set_attribute("gen_ai.usage.output_tokens", output_tokens)
            current_span.set_attribute("gen_ai.usage.completion_tokens", output_tokens)
        if input_tokens and output_tokens:
            current_span.set_attribute("gen_ai.usage.total_tokens", input_tokens + output_tokens)

        if request_id:
            current_span.set_attribute("gen_ai.response.id", request_id)

        # Legacy attributes for compatibility
        current_span.set_attribute("llm.model", model)
        if input_tokens:
            current_span.set_attribute("llm.input_tokens", input_tokens)
        if output_tokens:
            current_span.set_attribute("llm.output_tokens", output_tokens)

    log_agent_event(
        event_type="llm_call",
        status="success",
        metadata={
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }
    )


class AgentObservability:
    """High-level observability wrapper for the agent."""

    def __init__(self, session_id: str = None):
        self.session_id = session_id or self._generate_session_id()
        self.tracer = get_tracer()
        self.logger = get_logger()

    def _generate_session_id(self) -> str:
        import uuid
        return str(uuid.uuid4())

    def __enter__(self):
        log_agent_event("agent_session_start", metadata={"session_id": self.session_id})
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            log_agent_event(
                "agent_session_end",
                status="error",
                error=str(exc_val),
                metadata={"session_id": self.session_id}
            )
        else:
            log_agent_event(
                "agent_session_end",
                status="success",
                metadata={"session_id": self.session_id}
            )

        # Flush traces before Lambda exits
        flush_traces()

    @contextmanager
    def trace_agent_run(self, video_url: str):
        """Trace a complete agent run."""
        with trace_span("agent_run", {"video_url": video_url}) as span:
            # Set gen_ai attributes for the agent span
            span.set_attribute("gen_ai.system", "anthropic")
            span.set_attribute("gen_ai.operation.name", "agent_run")

            log_agent_event("agent_start", video_url=video_url)
            try:
                yield span
                log_agent_event("agent_complete", video_url=video_url)
            except Exception as e:
                log_agent_event("agent_error", video_url=video_url, status="error", error=str(e))
                raise


def flush_traces():
    """Force flush any pending traces."""
    try:
        provider = trace.get_tracer_provider()
        if hasattr(provider, 'force_flush'):
            provider.force_flush(timeout_millis=5000)
    except Exception as e:
        print(f"[Observability] Error flushing traces: {e}")
