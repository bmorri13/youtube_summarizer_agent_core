"""YouTube Analyzer tools — LangChain @tool format."""

from .youtube import get_transcript
from .channel import get_latest_channel_video
from .notes import (
    save_note,
    is_video_processed,
    mark_video_processed,
    update_channel_checked,
)
from .slack import send_slack_notification

# All LangChain tool objects for the agent
ALL_TOOLS = [get_transcript, get_latest_channel_video, save_note, send_slack_notification]

__all__ = [
    "get_transcript",
    "save_note",
    "send_slack_notification",
    "get_latest_channel_video",
    "is_video_processed",
    "mark_video_processed",
    "update_channel_checked",
    "ALL_TOOLS",
]
