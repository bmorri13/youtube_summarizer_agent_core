"""YouTube Analyzer tools."""

from .youtube import get_transcript, TOOL_DEFINITION as YOUTUBE_TOOL
from .notes import (
    save_note,
    is_video_processed,
    mark_video_processed,
    update_channel_checked,
    TOOL_DEFINITION as NOTES_TOOL,
)
from .slack import send_slack_notification, TOOL_DEFINITION as SLACK_TOOL
from .channel import get_latest_channel_video, TOOL_DEFINITION as CHANNEL_TOOL

# All tool definitions for Claude API
ALL_TOOLS = [YOUTUBE_TOOL, NOTES_TOOL, SLACK_TOOL, CHANNEL_TOOL]

__all__ = [
    "get_transcript",
    "save_note",
    "send_slack_notification",
    "get_latest_channel_video",
    "is_video_processed",
    "mark_video_processed",
    "update_channel_checked",
    "ALL_TOOLS",
    "YOUTUBE_TOOL",
    "NOTES_TOOL",
    "SLACK_TOOL",
    "CHANNEL_TOOL",
]
