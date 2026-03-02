#!/usr/bin/env python3
"""Local transcript fetcher — fetches transcripts and runs agent directly.

Runs on a homelab server (inside Docker) to bypass YouTube transcript
blocking that affects cloud IPs. Fetches transcripts locally and processes
them in-process via the agent.
"""

import os
import sys

from dotenv import load_dotenv
load_dotenv()

from youtube_transcript_api import YouTubeTranscriptApi

from agent import run_agent_with_transcript
from tools import is_video_processed
from tools.channel import _get_latest_channel_video_impl as get_latest_channel_video


def fetch_and_process(channel_url: str) -> bool:
    """Fetch latest video transcript and run agent to process it.

    Args:
        channel_url: YouTube channel URL to check for new videos

    Returns:
        True if processing was successful or video was already processed
    """
    print(f"Checking channel: {channel_url}")

    # 1. Get latest video from channel
    video_info = get_latest_channel_video(channel_url)

    if not video_info["success"]:
        print(f"  Failed to get video: {video_info.get('error')}")
        return False

    video_id = video_info["video_id"]

    # Check if already processed
    if is_video_processed(video_id):
        print(f"  Already processed: {video_info['title']}")
        return True

    print(f"  New video: {video_info['title']}")

    # 2. Fetch transcript locally (uses your home IP - not blocked!)
    try:
        ytt_api = YouTubeTranscriptApi()
        transcript_data = ytt_api.fetch(video_id)
        transcript_text = " ".join([t.text for t in transcript_data])
        print(f"  Transcript fetched: {len(transcript_text)} chars")
    except Exception as e:
        print(f"  Failed to fetch transcript: {e}")
        return False

    # 3. Run agent directly (in-process)
    try:
        result = run_agent_with_transcript(
            video_url=video_info["video_url"],
            video_id=video_id,
            video_title=video_info["title"],
            channel_id=video_info["channel_id"],
            channel_name=video_info["channel_name"],
            transcript=transcript_text,
        )
        print(f"  Agent completed successfully")
        return True
    except Exception as e:
        print(f"  Agent error: {e}")
        return False


def main():
    """Main entry point."""
    channels_str = os.getenv("MONITOR_CHANNEL_URLS", "")

    if not channels_str:
        print("Error: MONITOR_CHANNEL_URLS environment variable not set")
        sys.exit(1)

    channels = [c.strip() for c in channels_str.split(",") if c.strip()]

    if not channels:
        print("Error: No channels configured")
        sys.exit(1)

    print(f"Processing {len(channels)} channel(s)...")

    success_count = 0
    for channel_url in channels:
        if fetch_and_process(channel_url):
            success_count += 1

    print(f"\nDone: {success_count}/{len(channels)} channels processed successfully")


if __name__ == "__main__":
    main()
