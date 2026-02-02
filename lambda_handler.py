"""AWS Lambda handler for YouTube Analyzer Agent."""

import json
import os

from dotenv import load_dotenv
load_dotenv()

from opentelemetry import trace
from observability import get_logger, log_agent_event

from agent import run_agent, run_agent_with_transcript

logger = get_logger()


def handler(event, context):
    """AWS Lambda handler function.

    Expected event formats:

    Direct video analysis:
    {
        "video_url": "https://www.youtube.com/watch?v=VIDEO_ID"
    }

    Single channel check:
    {
        "channel_url": "https://www.youtube.com/@ChannelName"
    }

    Multiple channel check (scheduled runs):
    {
        "channel_urls": [
            "https://www.youtube.com/@Channel1",
            "https://www.youtube.com/@Channel2"
        ]
    }

    Or via API Gateway:
    {
        "body": "{\"video_url\": \"https://www.youtube.com/watch?v=VIDEO_ID\"}"
    }
    """
    # Get AWS request ID for tracing
    request_id = getattr(context, 'aws_request_id', None) if context else None

    # Determine trigger type
    trigger_type = "http" if "body" in event else "timer" if "channel_urls" in event else "direct"

    tracer = trace.get_tracer(__name__)

    with tracer.start_as_current_span("lambda_handler", attributes={
        "aws.request_id": request_id or "local",
        "faas.trigger": trigger_type,
    }) as span:
        try:
            # Handle pre-fetched transcript from local fetcher
            if isinstance(event, dict) and event.get("process_transcript"):
                return _process_prefetched_transcript(event)

            video_url = None
            channel_url = None
            channel_urls = None

            # Parse input
            if isinstance(event, dict):
                # Direct invocation format
                video_url = event.get("video_url")
                channel_url = event.get("channel_url")
                channel_urls = event.get("channel_urls")

                # API Gateway format (body is JSON string)
                if not any([video_url, channel_url, channel_urls]) and "body" in event:
                    try:
                        body = json.loads(event["body"]) if isinstance(event["body"], str) else event["body"]
                        video_url = body.get("video_url")
                        channel_url = body.get("channel_url")
                        channel_urls = body.get("channel_urls")
                    except (json.JSONDecodeError, TypeError):
                        pass

            # Log the invocation
            log_agent_event(
                "lambda_invocation",
                video_url=video_url,
                channel_url=channel_url,
                metadata={
                    "request_id": request_id,
                    "trigger_type": trigger_type,
                    "has_channel_urls": channel_urls is not None,
                }
            )

            # Handle multiple channels
            if channel_urls and isinstance(channel_urls, list):
                span.set_attribute("handler.type", "multiple_channels")
                span.set_attribute("handler.channel_count", len(channel_urls))
                return _process_multiple_channels(channel_urls)

            # Handle single channel
            if channel_url:
                span.set_attribute("handler.type", "single_channel")
                span.set_attribute("handler.channel_url", channel_url)
                return _process_single_url(channel_url, "channel_url")

            # Handle video URL
            if video_url:
                span.set_attribute("handler.type", "single_video")
                span.set_attribute("handler.video_url", video_url)
                return _process_single_url(video_url, "video_url")

            # No valid input
            log_agent_event("lambda_error", status="error", error="Missing required parameter")
            return {
                "statusCode": 400,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({
                    "error": "Missing required parameter: video_url, channel_url, or channel_urls",
                    "usage": {
                        "video_url": "https://www.youtube.com/watch?v=VIDEO_ID",
                        "channel_url": "https://www.youtube.com/@ChannelName",
                        "channel_urls": ["https://www.youtube.com/@Channel1", "https://www.youtube.com/@Channel2"]
                    }
                })
            }
        except Exception as e:
            log_agent_event("lambda_error", status="error", error=str(e))
            raise


def _process_prefetched_transcript(event: dict) -> dict:
    """Process a transcript that was pre-fetched by local fetcher.

    Args:
        event: Event containing video info and transcript from local fetcher

    Returns:
        Lambda response dict
    """
    tracer = trace.get_tracer(__name__)

    video_url = event["video_url"]
    video_title = event["video_title"]
    video_id = event["video_id"]
    channel_id = event.get("channel_id")
    channel_name = event["channel_name"]
    transcript = event["transcript"]

    with tracer.start_as_current_span("process_prefetched_transcript", attributes={
        "video_url": video_url,
        "video_id": video_id,
        "source": "local_fetcher",
        "transcript_length": len(transcript),
    }):
        log_agent_event(
            "prefetched_transcript",
            video_url=video_url,
            video_id=video_id,
            metadata={"source": "local_fetcher", "transcript_length": len(transcript)}
        )

        try:
            result = run_agent_with_transcript(
                video_url=video_url,
                video_id=video_id,
                video_title=video_title,
                channel_id=channel_id,
                channel_name=channel_name,
                transcript=transcript
            )

            log_agent_event(
                "prefetched_success",
                video_url=video_url,
                video_id=video_id,
            )

            return {
                "statusCode": 200,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"success": True, "result": result})
            }
        except Exception as e:
            log_agent_event(
                "prefetched_error",
                video_url=video_url,
                video_id=video_id,
                status="error",
                error=str(e)
            )
            return {
                "statusCode": 500,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"success": False, "error": str(e)})
            }


def _process_single_url(url: str, url_type: str) -> dict:
    """Process a single video or channel URL.

    Args:
        url: The video or channel URL
        url_type: Either "video_url" or "channel_url"

    Returns:
        Lambda response dict
    """
    tracer = trace.get_tracer(__name__)

    with tracer.start_as_current_span(f"process_{url_type}", attributes={
        url_type: url,
    }):
        try:
            result = run_agent(url)

            log_agent_event(
                "lambda_success",
                video_url=url if url_type == "video_url" else None,
                channel_url=url if url_type == "channel_url" else None,
            )

            return {
                "statusCode": 200,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({
                    url_type: url,
                    "result": result
                })
            }

        except Exception as e:
            log_agent_event(
                "lambda_error",
                video_url=url if url_type == "video_url" else None,
                channel_url=url if url_type == "channel_url" else None,
                status="error",
                error=str(e),
            )
            return {
                "statusCode": 500,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({
                    "error": str(e),
                    url_type: url
                })
            }


def _process_multiple_channels(channel_urls: list) -> dict:
    """Process multiple channel URLs for scheduled runs.

    Args:
        channel_urls: List of channel URLs to check

    Returns:
        Lambda response dict with results for each channel
    """
    tracer = trace.get_tracer(__name__)
    results = []

    with tracer.start_as_current_span("process_multiple_channels", attributes={
        "channel_count": len(channel_urls),
    }):
        for channel_url in channel_urls:
            if not channel_url or not isinstance(channel_url, str):
                continue

            channel_url = channel_url.strip()
            if not channel_url:
                continue

            with tracer.start_as_current_span("process_channel", attributes={
                "channel_url": channel_url,
            }):
                try:
                    result = run_agent(channel_url)
                    results.append({
                        "channel_url": channel_url,
                        "success": True,
                        "result": result
                    })
                    log_agent_event(
                        "channel_processed",
                        channel_url=channel_url,
                        status="success",
                    )
                except Exception as e:
                    results.append({
                        "channel_url": channel_url,
                        "success": False,
                        "error": str(e)
                    })
                    log_agent_event(
                        "channel_processed",
                        channel_url=channel_url,
                        status="error",
                        error=str(e),
                    )

        # Calculate summary
        successful = sum(1 for r in results if r["success"])
        failed = len(results) - successful

        log_agent_event(
            "batch_complete",
            metadata={
                "total": len(results),
                "successful": successful,
                "failed": failed,
            }
        )

        return {
            "statusCode": 200 if failed == 0 else 207,  # 207 Multi-Status for partial success
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "summary": {
                    "total": len(results),
                    "successful": successful,
                    "failed": failed
                },
                "results": results
            })
        }
