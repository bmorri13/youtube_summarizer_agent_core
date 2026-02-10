"""YouTube transcript and metadata fetching tool."""

import json
import re
import requests
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
)
from langchain_core.tools import tool


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


@tool
def get_transcript(video_url: str) -> str:
    """Fetch the transcript and metadata of a YouTube video. Returns the full text transcript along with video title, channel name, and URL.

    Args:
        video_url: YouTube video URL or video ID
    """
    video_id = extract_video_id(video_url)

    if not video_id:
        return json.dumps({
            "success": False,
            "error": f"Could not extract video ID from: {video_url}"
        })

    # Get video metadata
    metadata = get_video_metadata(video_id)

    try:
        # youtube-transcript-api v1.2.3+ uses instance method
        ytt_api = YouTubeTranscriptApi()
        transcript = ytt_api.fetch(video_id)

        # Combine all transcript snippets into full text
        full_transcript = " ".join(snippet.text for snippet in transcript)

        return json.dumps({
            "success": True,
            "video_id": video_id,
            "title": metadata["title"],
            "channel_name": metadata["channel_name"],
            "video_url": metadata["video_url"],
            "content": full_transcript
        })

    except TranscriptsDisabled:
        return json.dumps({
            "success": False,
            "error": f"Transcripts are disabled for video {video_id}",
            **metadata
        })
    except NoTranscriptFound:
        return json.dumps({
            "success": False,
            "error": f"No transcript found for video {video_id}",
            **metadata
        })
    except VideoUnavailable:
        return json.dumps({
            "success": False,
            "error": f"Video {video_id} is unavailable",
            **metadata
        })
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": f"Error fetching transcript: {str(e)}",
            **metadata
        })
