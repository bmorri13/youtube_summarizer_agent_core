#!/usr/bin/env python3
"""Local script to fetch transcripts and send to Lambda for processing.

This runs on a local machine (inside Docker) to bypass YouTube transcript
blocking that affects cloud IPs. It fetches transcripts locally and sends
them to AWS Lambda for the expensive AI processing.
"""

import json
import os
import sys

import boto3
from youtube_transcript_api import YouTubeTranscriptApi

from tools.channel import get_latest_channel_video


def is_video_processed_s3(video_id: str) -> bool:
    """Check if video was already processed by checking S3.

    Args:
        video_id: YouTube video ID to check

    Returns:
        True if video has already been processed, False otherwise
    """
    bucket = os.getenv("NOTES_S3_BUCKET")

    if not bucket:
        print("  Warning: NOTES_S3_BUCKET not set, cannot check processed status")
        return False

    s3_client = boto3.client("s3", region_name=os.getenv("AWS_REGION", "us-east-1"))

    try:
        # Check if processed_videos.json exists and contains this video
        # Note: Lambda saves to notes/processed_videos.json
        response = s3_client.get_object(Bucket=bucket, Key="notes/processed_videos.json")
        processed = json.loads(response["Body"].read().decode("utf-8"))
        return video_id in processed.get("videos", {})
    except s3_client.exceptions.NoSuchKey:
        return False
    except Exception as e:
        print(f"  Warning: Could not check S3: {e}")
        return False


def fetch_and_process(channel_url: str) -> bool:
    """Fetch latest video transcript and send to Lambda for processing.

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

    # Check S3 for processed status (source of truth)
    if is_video_processed_s3(video_id):
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

    # 3. Send to Lambda for processing (summarize, save notes, Slack)
    try:
        lambda_client = boto3.client(
            "lambda", region_name=os.getenv("AWS_REGION", "us-east-1")
        )

        payload = {
            "process_transcript": True,
            "video_id": video_id,
            "video_url": video_info["video_url"],
            "video_title": video_info["title"],
            "channel_id": video_info["channel_id"],
            "channel_name": video_info["channel_name"],
            "transcript": transcript_text,
        }

        response = lambda_client.invoke(
            FunctionName=os.getenv("LAMBDA_FUNCTION_NAME", "youtube-analyzer"),
            InvocationType="RequestResponse",
            Payload=json.dumps(payload),
        )

        result = json.loads(response["Payload"].read())
        print(f"  Lambda response: {result.get('statusCode', 'unknown')}")

        if result.get("statusCode") == 200:
            return True

    except Exception as e:
        print(f"  Failed to invoke Lambda: {e}")
        return False

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
