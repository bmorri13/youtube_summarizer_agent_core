"""Observability utilities - logging, sanitization, and trace flushing.

Provides:
- Structured logging (stdout captured by ECS awslogs / Lambda)
- Log injection prevention via input sanitization
- ADOT trace flush for Lambda (ensures spans are exported before cold shutdown)

LLM-level observability (prompts, completions, cost, evals) is handled by Langfuse.
Infrastructure tracing (HTTP latency, cold starts, Bedrock API errors) remains with ADOT/X-Ray.
"""

import os
import logging
import re
from typing import Any

from opentelemetry import trace


# Configuration
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

# Global state
_logger = None


def sanitize_log_value(value: Any, max_length: int = 1000) -> str:
    """Sanitize a value for safe logging to prevent log injection attacks.

    This function:
    - Converts value to string
    - Removes/escapes control characters (newlines, carriage returns, tabs)
    - Truncates overly long strings
    - Escapes characters that could forge log entries
    """
    if value is None:
        return "null"

    str_value = str(value)

    # Remove or escape control characters that could forge log entries
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
    """Recursively sanitize all string values in a dictionary for logging."""
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


def truncate_for_trace(value, max_length: int = 5000) -> str:
    """Truncate a value for Langfuse trace storage."""
    if value is None:
        return ""
    str_value = str(value)
    if len(str_value) > max_length:
        return str_value[:max_length] + f"...[truncated, {len(str_value)} total chars]"
    return str_value


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

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    console_handler.setFormatter(formatter)
    _logger.addHandler(console_handler)

    return _logger


def get_logger() -> logging.Logger:
    """Get or create the global logger."""
    global _logger
    if _logger is None:
        _logger = setup_logging()
    return _logger


def flush_traces():
    """Force flush pending ADOT traces and Langfuse events."""
    try:
        provider = trace.get_tracer_provider()
        if hasattr(provider, 'force_flush'):
            provider.force_flush(timeout_millis=5000)
    except Exception as e:
        print(f"[Observability] Error flushing ADOT traces: {e}")
    try:
        from langfuse import get_client
        get_client().flush()
    except Exception as e:
        print(f"[Observability] Error flushing Langfuse: {e}")
