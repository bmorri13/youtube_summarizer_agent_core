"""YouTube channel tool for fetching latest videos via RSS feed."""

import re
import xml.etree.ElementTree as ET

import requests


# Tool definition for Claude API
TOOL_DEFINITION = {
    "name": "get_latest_channel_video",
    "description": "Get the latest video from a YouTube channel. Returns video info including video_id, video_url, title, and published date. Also indicates if the video has already been processed.",
    "input_schema": {
        "type": "object",
        "properties": {
            "channel_url": {
                "type": "string",
                "description": "YouTube channel URL (supports @username, /channel/, /c/ formats)"
            }
        },
        "required": ["channel_url"]
    }
}


def extract_channel_id(channel_url: str) -> str:
    """Extract channel ID from various YouTube channel URL formats.

    Supports:
    - https://www.youtube.com/channel/UCxxxxxxx
    - https://www.youtube.com/@username
    - https://www.youtube.com/c/ChannelName
    - https://www.youtube.com/user/username

    For @username, /c/, and /user/ formats, we need to fetch the page
    to get the actual channel ID.

    Returns:
        Channel ID string (e.g., "UCxxxxxxx")

    Raises:
        ValueError: If channel ID cannot be extracted
    """
    # Clean up URL
    channel_url = channel_url.strip().rstrip('/')

    # Remove /videos suffix if present
    if channel_url.endswith('/videos'):
        channel_url = channel_url[:-7]

    # Direct channel ID format: /channel/UCxxxxxxx
    match = re.search(r'/channel/(UC[a-zA-Z0-9_-]+)', channel_url)
    if match:
        return match.group(1)

    # Handle @username, /c/, /user/ formats - need to fetch page to get channel ID
    if any(pattern in channel_url for pattern in ['/@', '/c/', '/user/']):
        return _fetch_channel_id_from_page(channel_url)

    raise ValueError(f"Could not extract channel ID from URL: {channel_url}")


def _fetch_channel_id_from_page(channel_url: str) -> str:
    """Fetch channel ID by scraping the channel page.

    YouTube embeds the channel ID in the page HTML as a meta tag
    or in the canonical URL.
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(channel_url, headers=headers, timeout=10)
        response.raise_for_status()

        # Look for channel ID in various patterns
        # Pattern 1: "channelId":"UCxxxxxxx"
        match = re.search(r'"channelId":"(UC[a-zA-Z0-9_-]+)"', response.text)
        if match:
            return match.group(1)

        # Pattern 2: /channel/UCxxxxxxx in canonical URL
        match = re.search(r'<link rel="canonical" href="[^"]+/channel/(UC[a-zA-Z0-9_-]+)"', response.text)
        if match:
            return match.group(1)

        # Pattern 3: externalId in page data
        match = re.search(r'"externalId":"(UC[a-zA-Z0-9_-]+)"', response.text)
        if match:
            return match.group(1)

        raise ValueError("Channel ID not found in page")

    except requests.RequestException as e:
        raise ValueError(f"Failed to fetch channel page: {e}")


def _get_video_duration(video_id: str) -> int:
    """Fetch video duration in seconds from YouTube.

    Args:
        video_id: YouTube video ID

    Returns:
        Duration in seconds, or 0 if unable to determine
    """
    try:
        # Fetch video page and look for duration in metadata
        url = f"https://www.youtube.com/watch?v={video_id}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        # Look for duration in various formats
        # Pattern 1: "lengthSeconds":"123"
        match = re.search(r'"lengthSeconds":"(\d+)"', response.text)
        if match:
            return int(match.group(1))

        # Pattern 2: "approxDurationMs":"123000"
        match = re.search(r'"approxDurationMs":"(\d+)"', response.text)
        if match:
            return int(match.group(1)) // 1000

        return 0
    except Exception:
        return 0


def get_latest_channel_video(channel_url: str, min_duration_seconds: int = 90) -> dict:
    """Fetch the latest full-length video from a YouTube channel using RSS feed.

    Skips YouTube Shorts (videos under min_duration_seconds).

    Args:
        channel_url: YouTube channel URL
        min_duration_seconds: Minimum video duration to consider (default 90s to skip Shorts)

    Returns:
        dict with:
            - success: bool
            - video_id: str (if successful)
            - video_url: str (if successful)
            - title: str (if successful)
            - published: str (if successful, ISO format)
            - channel_id: str (if successful)
            - channel_name: str (if successful)
            - duration_seconds: int (if successful)
            - is_already_processed: bool (if successful)
            - error: str (if failed)
    """
    from .notes import is_video_processed

    try:
        # Extract channel ID
        channel_id = extract_channel_id(channel_url)

        # Fetch RSS feed
        rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(rss_url, headers=headers, timeout=10)
        response.raise_for_status()

        # Parse XML
        root = ET.fromstring(response.content)

        # Define namespaces used in YouTube RSS
        namespaces = {
            'atom': 'http://www.w3.org/2005/Atom',
            'yt': 'http://www.youtube.com/xml/schemas/2015',
            'media': 'http://search.yahoo.com/mrss/'
        }

        # Get channel name from feed title
        channel_name = root.find('atom:title', namespaces)
        channel_name = channel_name.text if channel_name is not None else "Unknown Channel"

        # Get all entries and find the first non-Short video
        entries = root.findall('atom:entry', namespaces)
        if not entries:
            return {
                "success": False,
                "error": "No videos found in channel feed"
            }

        for entry in entries:
            video_id_elem = entry.find('yt:videoId', namespaces)
            if video_id_elem is None:
                continue

            video_id = video_id_elem.text

            # Check video duration to filter out Shorts
            duration = _get_video_duration(video_id)
            if duration > 0 and duration < min_duration_seconds:
                # This is likely a Short, skip it
                continue

            title_elem = entry.find('atom:title', namespaces)
            published_elem = entry.find('atom:published', namespaces)

            title = title_elem.text if title_elem is not None else "Unknown Title"
            published = published_elem.text if published_elem is not None else None

            video_url = f"https://www.youtube.com/watch?v={video_id}"

            # Check if already processed
            already_processed = is_video_processed(video_id)

            return {
                "success": True,
                "video_id": video_id,
                "video_url": video_url,
                "title": title,
                "published": published,
                "channel_id": channel_id,
                "channel_name": channel_name,
                "duration_seconds": duration,
                "is_already_processed": already_processed
            }

        # All videos in feed were Shorts
        return {
            "success": False,
            "error": f"No full-length videos found (all {len(entries)} videos were under {min_duration_seconds}s)"
        }

    except ValueError as e:
        return {
            "success": False,
            "error": str(e)
        }
    except requests.RequestException as e:
        return {
            "success": False,
            "error": f"Failed to fetch RSS feed: {e}"
        }
    except ET.ParseError as e:
        return {
            "success": False,
            "error": f"Failed to parse RSS feed: {e}"
        }
