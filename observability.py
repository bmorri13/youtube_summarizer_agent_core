"""AWS AgentCore Observability - Tracing and Logging.

This module provides observability features for the YouTube Analyzer Agent.
When running in AWS Lambda with ADOT (AWS Distro for OpenTelemetry), tracing
is automatically configured via environment variables. This module provides:
- CloudWatch logging via watchtower
- Custom span helpers for agent-specific tracing
- Structured event logging for monitoring
"""

import os
import logging
import json
from datetime import datetime
from functools import wraps
from typing import Callable
from contextlib import contextmanager

import boto3

# OpenTelemetry imports - ADOT provides the TracerProvider automatically
from opentelemetry import trace, baggage
from opentelemetry.context import attach, detach
from opentelemetry.trace import Status, StatusCode

# CloudWatch logging
try:
    import watchtower
    WATCHTOWER_AVAILABLE = True
except ImportError:
    WATCHTOWER_AVAILABLE = False


# Configuration
SERVICE_NAME = os.environ.get("OTEL_SERVICE_NAME", "youtube-analyzer-agent")
LOG_GROUP_NAME = os.environ.get("CLOUDWATCH_LOG_GROUP", "/aws/bedrock-agentcore/youtube-analyzer")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

# Check if running in Lambda with ADOT (ADOT sets this)
ADOT_ENABLED = os.environ.get("AWS_LAMBDA_EXEC_WRAPPER") == "/opt/otel-instrument"

# Global logger
_logger = None


def setup_logging() -> logging.Logger:
    """Initialize CloudWatch logging."""
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

    # CloudWatch handler for AWS deployment
    if WATCHTOWER_AVAILABLE and (ADOT_ENABLED or os.environ.get("AGENT_OBSERVABILITY_ENABLED", "").lower() == "true"):
        try:
            # Create CloudWatch client with explicit region
            logs_client = boto3.client('logs', region_name=AWS_REGION)

            cloudwatch_handler = watchtower.CloudWatchLogHandler(
                log_group_name=LOG_GROUP_NAME,
                log_stream_name=f"agent-{datetime.now().strftime('%Y-%m-%d-%H')}",
                boto3_client=logs_client,
                create_log_group=True,
            )
            cloudwatch_handler.setLevel(logging.INFO)
            cloudwatch_handler.setFormatter(logging.Formatter(
                '%(message)s'
            ))
            _logger.addHandler(cloudwatch_handler)
            print(f"[Observability] CloudWatch logging enabled: {LOG_GROUP_NAME}")
        except Exception as e:
            print(f"[Observability] Failed to setup CloudWatch logging: {e}")

    return _logger


def get_tracer() -> trace.Tracer:
    """Get the tracer (provided by ADOT or default no-op tracer)."""
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
                span.set_attribute(key, str(value))

        logger.info(json.dumps({
            "event": "span_start",
            "span_name": name,
            "attributes": attributes or {}
        }))

        try:
            yield span
            span.set_status(Status(StatusCode.OK))
            logger.info(json.dumps({
                "event": "span_end",
                "span_name": name,
                "status": "OK"
            }))
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            logger.error(json.dumps({
                "event": "span_error",
                "span_name": name,
                "error": str(e)
            }))
            raise


def trace_function(name: str = None, capture_args: bool = False):
    """Decorator to trace a function execution.

    Usage:
        @trace_function("process_video")
        def process_video(video_url):
            ...
    """
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


def set_session_id(session_id: str):
    """Set the session ID for distributed tracing."""
    ctx = baggage.set_baggage("session.id", session_id)
    token = attach(ctx)
    return token


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
        "event_type": event_type,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "status": status,
        "service": SERVICE_NAME,
    }

    if video_url:
        event["video_url"] = video_url
    if video_id:
        event["video_id"] = video_id
    if channel_url:
        event["channel_url"] = channel_url
    if is_already_processed is not None:
        event["is_already_processed"] = is_already_processed
    if tool_name:
        event["tool_name"] = tool_name
    if error:
        event["error"] = error
    if metadata:
        event["metadata"] = metadata

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


def log_llm_call(model: str, input_tokens: int = None, output_tokens: int = None):
    """Log an LLM API call."""
    current_span = trace.get_current_span()
    if current_span and current_span.get_span_context().is_valid:
        current_span.set_attribute("llm.model", model)
        if input_tokens:
            current_span.set_attribute("llm.input_tokens", input_tokens)
        if output_tokens:
            current_span.set_attribute("llm.output_tokens", output_tokens)
        current_span.set_attribute("gen_ai.system", "anthropic")
        current_span.set_attribute("gen_ai.request.model", model)

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
        self._token = None

    def _generate_session_id(self) -> str:
        import uuid
        return str(uuid.uuid4())

    def __enter__(self):
        self._token = set_session_id(self.session_id)
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

        if self._token:
            detach(self._token)

    @contextmanager
    def trace_agent_run(self, video_url: str):
        """Trace a complete agent run."""
        with trace_span("agent_run", {"video_url": video_url}) as span:
            log_agent_event("agent_start", video_url=video_url)
            try:
                yield span
                log_agent_event("agent_complete", video_url=video_url)
            except Exception as e:
                log_agent_event("agent_error", video_url=video_url, status="error", error=str(e))
                raise


def flush_traces():
    """Force flush any pending traces."""
    provider = trace.get_tracer_provider()
    if hasattr(provider, 'force_flush'):
        provider.force_flush()
