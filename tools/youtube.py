"""YouTube transcript and metadata fetching tool."""

import re
import requests
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
)


# Tool definition for Claude API
TOOL_DEFINITION = {
    "name": "get_transcript",
    "description": "Fetch the transcript and metadata of a YouTube video. Returns the full text transcript along with video title, channel name, and URL.",
    "input_schema": {
        "type": "object",
        "properties": {
            "video_url": {
                "type": "string",
                "description": "YouTube video URL or video ID"
            }
        },
        "required": ["video_url"]
    }
}


def extract_video_id(url: str) -> str | None:
    """Extract video ID from various YouTube URL formats."""
    patterns = [
        r'(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([a-zA-Z0-9_-]{11})',
        r'^([a-zA-Z0-9_-]{11})$',  # Raw video ID
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def get_video_metadata(video_id: str) -> dict:
    """Fetch video metadata using oembed API (no API key required)."""
    try:
        url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        return {
            "title": data.get("title", "Unknown Title"),
            "channel_name": data.get("author_name", "Unknown Channel"),
            "video_url": f"https://www.youtube.com/watch?v={video_id}"
        }
    except Exception:
        return {
            "title": "Unknown Title",
            "channel_name": "Unknown Channel",
            "video_url": f"https://www.youtube.com/watch?v={video_id}"
        }


def get_transcript(video_url: str) -> dict:
    """Fetch YouTube video transcript and metadata.

    Returns:
        dict with 'success', 'content', 'title', 'channel_name', 'video_url' or 'error' keys
    """
    video_id = extract_video_id(video_url)

    if not video_id:
        return {
            "success": False,
            "error": f"Could not extract video ID from: {video_url}"
        }

    # Get video metadata
    metadata = get_video_metadata(video_id)

    try:
        # youtube-transcript-api v1.2.3+ uses instance method
        ytt_api = YouTubeTranscriptApi()
        transcript = ytt_api.fetch(video_id)

        # Combine all transcript snippets into full text
        full_transcript = " ".join(snippet.text for snippet in transcript)

        return {
            "success": True,
            "video_id": video_id,
            "title": metadata["title"],
            "channel_name": metadata["channel_name"],
            "video_url": metadata["video_url"],
            "content": full_transcript
        }

    except TranscriptsDisabled:
        return {
            "success": False,
            "error": f"Transcripts are disabled for video {video_id}",
            **metadata
        }
    except NoTranscriptFound:
        return {
            "success": False,
            "error": f"No transcript found for video {video_id}",
            **metadata
        }
    except VideoUnavailable:
        return {
            "success": False,
            "error": f"Video {video_id} is unavailable",
            **metadata
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Error fetching transcript: {str(e)}",
            **metadata
        }
