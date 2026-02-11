#!/usr/bin/env python3
"""Local script to fetch transcripts and send to Lambda for processing.

This runs on a local machine (inside Docker) to bypass YouTube transcript
blocking that affects cloud IPs. It fetches transcripts locally and sends
them to AWS Lambda for the expensive AI processing.
"""

import json
import os
import sys
import time

import boto3
from botocore.config import Config
from youtube_transcript_api import YouTubeTranscriptApi

from tools.channel import _get_latest_channel_video_impl as get_latest_channel_video


def is_video_processed_s3(video_id: str, max_retries: int = 2) -> bool:
    """Check if video was already processed by checking S3.

    Uses retry logic for transient S3 errors. On persistent failure,
    returns True (safe default: skip rather than risk re-processing).

    Args:
        video_id: YouTube video ID to check
        max_retries: Number of retries on transient errors

    Returns:
        True if video has already been processed or check failed (safe default)
        False only if confirmed not processed
    """
    bucket = os.getenv("NOTES_S3_BUCKET")

    if not bucket:
        print("  Warning: NOTES_S3_BUCKET not set, cannot check processed status")
        return True  # Safe default: skip

    s3_client = boto3.client("s3", region_name=os.getenv("AWS_REGION", "us-east-1"))

    key = "metadata/processed_videos.json"

    for attempt in range(max_retries + 1):
        try:
            response = s3_client.get_object(Bucket=bucket, Key=key)
            raw_body = response["Body"].read().decode("utf-8")
            processed = json.loads(raw_body)
            videos = processed.get("videos", {})
            found = video_id in videos
            print(f"  S3 check: {key} has {len(videos)} videos, "
                  f"{video_id} found={found}")
            return found
        except s3_client.exceptions.NoSuchKey:
            print(f"  S3 check: {key} does not exist, checking fallback")
            # Fallback: check old location for backwards compatibility
            try:
                response = s3_client.get_object(
                    Bucket=bucket, Key="notes/processed_videos.json"
                )
                raw_body = response["Body"].read().decode("utf-8")
                processed = json.loads(raw_body)
                videos = processed.get("videos", {})
                found = video_id in videos
                print(f"  S3 check: fallback notes/ has {len(videos)} videos, "
                      f"{video_id} found={found}")
                return found
            except s3_client.exceptions.NoSuchKey:
                print("  S3 check: no index file in either location")
                return False
            except Exception as e:
                print(f"  S3 check: fallback read failed: {e}")
                return False
        except Exception as e:
            if attempt < max_retries:
                print(f"  Warning: S3 check failed (attempt {attempt + 1}), retrying: {e}")
                time.sleep(1)
            else:
                print(f"  Error: Could not check S3 after {max_retries + 1} attempts: {e}")
                print("  Assuming video is already processed (safe default)")
                return True  # Safe default: skip rather than re-process


def mark_video_processing_s3(
    video_id: str, title: str, channel_id: str, channel_name: str
) -> bool:
    """Mark video as processing in S3 BEFORE invoking Lambda.

    This prevents race conditions where multiple fetchers process the same video.
    The video entry is created with status "processing" before Lambda is invoked.
    Lambda will later update this to "processed" with the note path.

    Args:
        video_id: YouTube video ID
        title: Video title
        channel_id: YouTube channel ID
        channel_name: Channel name

    Returns:
        True if successfully marked as processing, False if already exists or error
    """
    bucket = os.getenv("NOTES_S3_BUCKET")

    if not bucket:
        print("  Warning: NOTES_S3_BUCKET not set, cannot mark as processing")
        return False

    s3_client = boto3.client("s3", region_name=os.getenv("AWS_REGION", "us-east-1"))
    key = "metadata/processed_videos.json"

    try:
        # Load current index (check metadata/ then fallback to notes/)
        try:
            response = s3_client.get_object(Bucket=bucket, Key=key)
            processed = json.loads(response["Body"].read().decode("utf-8"))
        except s3_client.exceptions.NoSuchKey:
            try:
                response = s3_client.get_object(
                    Bucket=bucket, Key="notes/processed_videos.json"
                )
                processed = json.loads(response["Body"].read().decode("utf-8"))
            except s3_client.exceptions.NoSuchKey:
                processed = {"videos": {}, "channels": {}}

        # Double-check not already present (in case of race)
        if video_id in processed.get("videos", {}):
            return False  # Already being processed

        # Mark as processing
        from datetime import datetime

        processed["videos"][video_id] = {
            "processing_started": datetime.now().isoformat(),
            "status": "processing",
            "title": title,
            "channel_id": channel_id,
            "channel_name": channel_name,
        }

        # Save back to S3
        s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=json.dumps(processed, indent=2).encode("utf-8"),
            ContentType="application/json",
        )
        return True

    except Exception as e:
        print(f"  Warning: Could not mark video as processing: {e}")
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

    # 3. Mark as processing BEFORE invoking Lambda to prevent race conditions
    if not mark_video_processing_s3(
        video_id,
        video_info["title"],
        video_info["channel_id"],
        video_info["channel_name"],
    ):
        print("  Video already being processed by another instance")
        return True

    # 4. Send to Lambda for processing (summarize, save notes, Slack)
    try:
        lambda_client = boto3.client(
            "lambda",
            region_name=os.getenv("AWS_REGION", "us-east-1"),
            config=Config(
                read_timeout=600,  # Lambda can take up to 5min
                retries={"max_attempts": 0},  # No retries — prevent duplicate processing
            ),
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
