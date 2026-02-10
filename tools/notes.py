"""Note saving tool with local filesystem and S3 backends."""

import json
import logging
import os
import re
from datetime import datetime

from langchain_core.tools import tool as langchain_tool

logger = logging.getLogger(__name__)

PROCESSED_VIDEOS_FILE = "processed_videos.json"
AWS_REGION = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))


class ProcessedIndexLoadError(Exception):
    """Raised when the processed videos index cannot be loaded from storage.

    This prevents callers from writing back incomplete data that would
    overwrite the existing index.
    """
    pass


def sanitize_filename(title: str) -> str:
    """Convert title to safe filename."""
    safe = re.sub(r'[<>:"/\\|?*]', '', title)
    safe = safe.replace(' ', '_')
    return safe[:100]


def save_to_local(title: str, content: str, directory: str) -> str:
    """Save note to local filesystem."""
    os.makedirs(directory, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{sanitize_filename(title)}.md"
    filepath = os.path.join(directory, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n")
        f.write(f"*Generated: {datetime.now().isoformat()}*\n\n")
        f.write(content)

    return filepath


def save_to_s3(title: str, content: str, bucket: str) -> str:
    """Save note to S3 bucket."""
    import boto3

    s3 = boto3.client("s3", region_name=AWS_REGION)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{sanitize_filename(title)}.md"
    key = f"notes/{filename}"

    full_content = f"# {title}\n\n*Generated: {datetime.now().isoformat()}*\n\n{content}"

    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=full_content.encode("utf-8"),
        ContentType="text/markdown"
    )

    return f"s3://{bucket}/{key}"


@langchain_tool
def save_note(
    title: str,
    content: str,
    video_id: str = None,
    channel_id: str = None,
    channel_name: str = None
) -> str:
    """Save a summary or note to storage (local filesystem or S3). Returns the path where the note was saved. For YouTube videos, include video_id, channel_id, and channel_name to track the video as processed.

    Args:
        title: Title for the note
        content: Content of the note (markdown supported)
        video_id: YouTube video ID (optional, for tracking processed videos)
        channel_id: YouTube channel ID (optional, for tracking processed videos)
        channel_name: YouTube channel name (optional, for tracking processed videos)
    """
    if not content:
        return json.dumps({
            "success": False,
            "error": "Note content cannot be empty"
        })

    backend = os.environ.get("NOTES_BACKEND", "local")

    try:
        if backend == "s3":
            bucket = os.environ.get("NOTES_S3_BUCKET")
            if not bucket:
                return json.dumps({
                    "success": False,
                    "error": "NOTES_S3_BUCKET not configured"
                })
            path = save_to_s3(title, content, bucket)
        else:
            directory = os.environ.get("NOTES_LOCAL_DIR", "./notes")
            path = save_to_local(title, content, directory)

        # Track video as processed if video_id provided
        if video_id:
            mark_video_processed(
                video_id=video_id,
                title=title,
                channel_id=channel_id or "",
                channel_name=channel_name or "",
                note_path=path
            )

        return json.dumps({
            "success": True,
            "path": path
        })

    except Exception as e:
        return json.dumps({
            "success": False,
            "error": f"Error saving note: {str(e)}"
        })


# ============================================
# Processed Videos Tracking
# ============================================

def _get_processed_index_path() -> str:
    """Get the path to the processed videos index file."""
    backend = os.environ.get("NOTES_BACKEND", "local")
    if backend == "s3":
        return f"metadata/{PROCESSED_VIDEOS_FILE}"
    else:
        directory = os.environ.get("NOTES_LOCAL_DIR", "./notes")
        return os.path.join(directory, PROCESSED_VIDEOS_FILE)


def load_processed_index() -> dict:
    """Load the processed videos index from storage.

    Returns:
        dict with 'videos' and 'channels' keys

    Raises:
        ProcessedIndexLoadError: If the index cannot be loaded due to a
            transient or unexpected error (NOT a missing file). This prevents
            callers from writing back incomplete data.
    """
    backend = os.environ.get("NOTES_BACKEND", "local")

    empty_index = {"videos": {}, "channels": {}}

    try:
        if backend == "s3":
            return _load_index_from_s3()
        else:
            return _load_index_from_local()
    except FileNotFoundError:
        return empty_index
    except Exception as e:
        logger.error(f"Failed to load processed index: {e}", exc_info=True)
        raise ProcessedIndexLoadError(
            f"Could not load processed index: {e}"
        ) from e


def _load_index_from_local() -> dict:
    """Load index from local filesystem."""
    path = _get_processed_index_path()

    if not os.path.exists(path):
        raise FileNotFoundError(f"Index file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_index_from_s3() -> dict:
    """Load index from S3."""
    import boto3
    from botocore.exceptions import ClientError

    bucket = os.environ.get("NOTES_S3_BUCKET")
    if not bucket:
        raise ValueError("NOTES_S3_BUCKET not configured")

    s3 = boto3.client("s3", region_name=AWS_REGION)
    key = f"metadata/{PROCESSED_VIDEOS_FILE}"

    try:
        response = s3.get_object(Bucket=bucket, Key=key)
        return json.loads(response["Body"].read().decode("utf-8"))
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchKey":
            # Fallback: check old location for backwards compatibility
            try:
                response = s3.get_object(Bucket=bucket, Key=f"notes/{PROCESSED_VIDEOS_FILE}")
                return json.loads(response["Body"].read().decode("utf-8"))
            except ClientError:
                raise FileNotFoundError(f"Index file not found: s3://{bucket}/{key}")
        raise


def save_processed_index(index: dict) -> None:
    """Save the processed videos index to storage.

    Args:
        index: dict with 'videos' and 'channels' keys
    """
    backend = os.environ.get("NOTES_BACKEND", "local")

    if backend == "s3":
        _save_index_to_s3(index)
    else:
        _save_index_to_local(index)


def _save_index_to_local(index: dict) -> None:
    """Save index to local filesystem."""
    directory = os.environ.get("NOTES_LOCAL_DIR", "./notes")
    os.makedirs(directory, exist_ok=True)

    path = os.path.join(directory, PROCESSED_VIDEOS_FILE)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2)


def _save_index_to_s3(index: dict) -> None:
    """Save index to S3."""
    import boto3

    bucket = os.environ.get("NOTES_S3_BUCKET")
    if not bucket:
        raise ValueError("NOTES_S3_BUCKET not configured")

    s3 = boto3.client("s3", region_name=AWS_REGION)
    key = f"metadata/{PROCESSED_VIDEOS_FILE}"

    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(index, indent=2).encode("utf-8"),
        ContentType="application/json"
    )


def is_video_processed(video_id: str) -> bool:
    """Check if a video has already been processed.

    Returns True (safe default) if the index cannot be loaded, to prevent
    re-processing on transient errors.

    Args:
        video_id: YouTube video ID

    Returns:
        True if video has been processed or index can't be loaded, False otherwise
    """
    try:
        index = load_processed_index()
    except ProcessedIndexLoadError:
        logger.error(
            f"Assuming video {video_id} is processed: could not load index safely"
        )
        return True
    return video_id in index.get("videos", {})


def mark_video_processed(
    video_id: str,
    title: str,
    channel_id: str,
    channel_name: str,
    note_path: str
) -> None:
    """Mark a video as processed in the index.

    Updates existing entry if present (preserves processing_started timestamp
    from when local_fetcher marked it as "processing").

    If the index cannot be loaded (transient S3 error), the write is skipped
    to prevent overwriting the existing index with incomplete data.

    Args:
        video_id: YouTube video ID
        title: Video title
        channel_id: YouTube channel ID
        channel_name: Channel name
        note_path: Path where the note was saved
    """
    try:
        index = load_processed_index()
    except ProcessedIndexLoadError:
        logger.error(
            f"Skipping mark_video_processed for {video_id}: "
            "could not load index safely"
        )
        return

    if "videos" not in index:
        index["videos"] = {}

    # Preserve processing_started timestamp if it exists (set by local_fetcher)
    existing = index["videos"].get(video_id, {})

    index["videos"][video_id] = {
        "processed_at": datetime.now().isoformat(),
        "processing_started": existing.get("processing_started"),
        "status": "processed",
        "title": title,
        "channel_id": channel_id,
        "channel_name": channel_name,
        "note_path": note_path
    }

    save_processed_index(index)


def update_channel_checked(
    channel_id: str,
    channel_name: str,
    channel_url: str,
    last_video_id: str
) -> None:
    """Update the last checked time for a channel.

    If the index cannot be loaded (transient S3 error), the write is skipped
    to prevent overwriting the existing index with incomplete data.

    Args:
        channel_id: YouTube channel ID
        channel_name: Channel name
        channel_url: Channel URL
        last_video_id: ID of the latest video found
    """
    try:
        index = load_processed_index()
    except ProcessedIndexLoadError:
        logger.error(
            f"Skipping update_channel_checked for {channel_id}: "
            "could not load index safely"
        )
        return

    if "channels" not in index:
        index["channels"] = {}

    index["channels"][channel_id] = {
        "name": channel_name,
        "url": channel_url,
        "last_checked": datetime.now().isoformat(),
        "last_video_id": last_video_id
    }

    save_processed_index(index)
