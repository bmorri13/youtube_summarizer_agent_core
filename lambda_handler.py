"""AWS Lambda handler for YouTube Analyzer Agent."""

import json

from dotenv import load_dotenv
load_dotenv()

from observability import get_logger, flush_traces
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
    try:
        # Handle pre-fetched transcript from local fetcher
        is_prefetched = isinstance(event, dict) and event.get("process_transcript")
        if is_prefetched:
            return _process_prefetched_transcript(event)

        video_url = None
        channel_url = None
        channel_urls = None

        # Parse input
        if isinstance(event, dict):
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

        logger.info(json.dumps({
            "event": "lambda_invocation",
            "has_video_url": video_url is not None,
            "has_channel_url": channel_url is not None,
            "has_channel_urls": channel_urls is not None,
        }))

        # Handle multiple channels
        if channel_urls and isinstance(channel_urls, list):
            return _process_multiple_channels(channel_urls)

        # Handle single channel
        if channel_url:
            return _process_single_url(channel_url, "channel_url")

        # Handle video URL
        if video_url:
            return _process_single_url(video_url, "video_url")

        # No valid input
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
        logger.error(f"Lambda handler error: {e}")
        raise
    finally:
        flush_traces()


def _process_prefetched_transcript(event: dict) -> dict:
    """Process a transcript that was pre-fetched by local fetcher."""
    video_url = event["video_url"]
    video_title = event["video_title"]
    video_id = event["video_id"]
    channel_id = event.get("channel_id")
    channel_name = event["channel_name"]
    transcript = event["transcript"]

    logger.info(json.dumps({
        "event": "prefetched_transcript",
        "video_id": video_id,
        "transcript_length": len(transcript),
    }))

    try:
        result = run_agent_with_transcript(
            video_url=video_url,
            video_id=video_id,
            video_title=video_title,
            channel_id=channel_id,
            channel_name=channel_name,
            transcript=transcript,
        )

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"success": True, "result": result})
        }
    except Exception as e:
        logger.error(f"Prefetched transcript error: {e}")
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"success": False, "error": str(e)})
        }


def _process_single_url(url: str, url_type: str) -> dict:
    """Process a single video or channel URL."""
    try:
        result = run_agent(url)

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                url_type: url,
                "result": result
            })
        }

    except Exception as e:
        logger.error(f"Error processing {url_type} {url}: {e}")
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "error": str(e),
                url_type: url
            })
        }


def _process_multiple_channels(channel_urls: list) -> dict:
    """Process multiple channel URLs for scheduled runs."""
    results = []

    for channel_url in channel_urls:
        if not channel_url or not isinstance(channel_url, str):
            continue

        channel_url = channel_url.strip()
        if not channel_url:
            continue

        try:
            result = run_agent(channel_url)
            results.append({
                "channel_url": channel_url,
                "success": True,
                "result": result
            })
        except Exception as e:
            results.append({
                "channel_url": channel_url,
                "success": False,
                "error": str(e)
            })
            logger.error(f"Channel processing error for {channel_url}: {e}")

    successful = sum(1 for r in results if r["success"])
    failed = len(results) - successful

    logger.info(json.dumps({
        "event": "batch_complete",
        "total": len(results),
        "successful": successful,
        "failed": failed,
    }))

    return {
        "statusCode": 200 if failed == 0 else 207,
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
