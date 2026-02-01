"""Slack notification tool with Block Kit formatting."""

import json
import os
import requests


# Tool definition for Claude API
TOOL_DEFINITION = {
    "name": "send_slack_notification",
    "description": "Send a formatted notification message to Slack with video analysis summary. Uses Slack Block Kit for clean formatting.",
    "input_schema": {
        "type": "object",
        "properties": {
            "video_title": {
                "type": "string",
                "description": "Title of the YouTube video"
            },
            "channel_name": {
                "type": "string",
                "description": "Name of the YouTube channel"
            },
            "video_url": {
                "type": "string",
                "description": "URL of the YouTube video"
            },
            "overview": {
                "type": "string",
                "description": "Brief 1-2 sentence overview of the video"
            },
            "key_points": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of 3-5 key takeaways from the video"
            },
            "main_takeaway": {
                "type": "string",
                "description": "The single most important insight from the video"
            }
        },
        "required": ["video_title", "channel_name", "video_url", "overview", "key_points"]
    }
}


def build_slack_blocks(
    video_title: str,
    channel_name: str,
    video_url: str,
    overview: str,
    key_points: list[str],
    main_takeaway: str | None = None
) -> list[dict]:
    """Build Slack Block Kit blocks for the notification."""
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "📹 YouTube Video Analysis Complete",
                "emoji": True
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*{video_title}*\n_{channel_name}_"
            }
        },
        {
            "type": "divider"
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Overview*\n{overview}"
            }
        }
    ]

    # Add main takeaway if provided
    if main_takeaway:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*🎯 Main Takeaway*\n{main_takeaway}"
            }
        })

    # Add key points
    key_points_text = "\n".join(f"• {point}" for point in key_points)
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*📌 Key Points*\n{key_points_text}"
        }
    })

    # Add divider and video link
    blocks.extend([
        {
            "type": "divider"
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"<{video_url}|▶️ Watch on YouTube>"
                }
            ]
        }
    ])

    return blocks


def send_via_webhook(blocks: list[dict], fallback_text: str, webhook_url: str) -> dict:
    """Send message via Slack webhook with blocks."""
    payload = {
        "text": fallback_text,  # Fallback for notifications
        "blocks": blocks
    }
    response = requests.post(
        webhook_url,
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=10
    )
    response.raise_for_status()
    return {"method": "webhook", "status": "sent"}


def send_via_bot(blocks: list[dict], fallback_text: str, token: str, channel: str) -> dict:
    """Send message via Slack bot token with blocks."""
    payload = {
        "channel": channel,
        "text": fallback_text,
        "blocks": blocks
    }
    response = requests.post(
        "https://slack.com/api/chat.postMessage",
        json=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        },
        timeout=10
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise Exception(f"Slack API error: {data.get('error', 'Unknown error')}")
    return {"method": "bot", "status": "sent", "channel": channel}


def send_slack_notification(
    video_title: str = "",
    channel_name: str = "",
    video_url: str = "",
    overview: str = "",
    key_points: list[str] | None = None,
    main_takeaway: str | None = None,
    # Legacy support for simple message
    message: str | None = None,
    channel: str | None = None
) -> dict:
    """Send Slack notification with formatted blocks.

    Returns:
        dict with 'success', 'method' or 'error' keys
    """
    # Legacy support: if only message is provided, use simple format
    if message and not video_title:
        return _send_simple_message(message, channel)

    if not video_title or not overview:
        return {
            "success": False,
            "error": "video_title and overview are required"
        }

    key_points = key_points or []

    # Build the blocks
    blocks = build_slack_blocks(
        video_title=video_title,
        channel_name=channel_name,
        video_url=video_url,
        overview=overview,
        key_points=key_points,
        main_takeaway=main_takeaway
    )

    # Fallback text for notifications
    fallback_text = f"YouTube Analysis: {video_title} - {overview[:100]}..."

    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    bot_token = os.environ.get("SLACK_BOT_TOKEN")
    default_channel = os.environ.get("SLACK_DEFAULT_CHANNEL", "#youtube-summaries")

    try:
        if webhook_url:
            send_via_webhook(blocks, fallback_text, webhook_url)
            return {
                "success": True,
                "method": "webhook"
            }
        elif bot_token:
            target_channel = channel or default_channel
            send_via_bot(blocks, fallback_text, bot_token, target_channel)
            return {
                "success": True,
                "method": "bot",
                "channel": target_channel
            }
        else:
            return {
                "success": True,
                "skipped": True,
                "message": "No Slack configuration found. Notification skipped."
            }

    except requests.exceptions.Timeout:
        return {
            "success": False,
            "error": "Slack request timed out"
        }
    except requests.exceptions.RequestException as e:
        return {
            "success": False,
            "error": f"Error sending Slack notification: {str(e)}"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def _send_simple_message(message: str, channel: str | None = None) -> dict:
    """Legacy: Send a simple text message."""
    if not message:
        return {
            "success": False,
            "error": "Message cannot be empty"
        }

    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    bot_token = os.environ.get("SLACK_BOT_TOKEN")
    default_channel = os.environ.get("SLACK_DEFAULT_CHANNEL", "#youtube-summaries")

    try:
        if webhook_url:
            response = requests.post(
                webhook_url,
                json={"text": message},
                headers={"Content-Type": "application/json"},
                timeout=10
            )
            response.raise_for_status()
            return {"success": True, "method": "webhook"}
        elif bot_token:
            target_channel = channel or default_channel
            response = requests.post(
                "https://slack.com/api/chat.postMessage",
                json={"channel": target_channel, "text": message},
                headers={
                    "Authorization": f"Bearer {bot_token}",
                    "Content-Type": "application/json"
                },
                timeout=10
            )
            response.raise_for_status()
            return {"success": True, "method": "bot", "channel": target_channel}
        else:
            return {"success": True, "skipped": True, "message": "No Slack config."}
    except Exception as e:
        return {"success": False, "error": str(e)}
