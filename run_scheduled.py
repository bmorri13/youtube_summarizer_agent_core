#!/usr/bin/env python3
"""Entry point for scheduled channel monitoring.

This script checks configured YouTube channels for new videos and processes
any that haven't been analyzed yet. Designed for scheduled runs (e.g., hourly
via AWS EventBridge or cron).

Usage:
    # Single channel via environment
    MONITOR_CHANNEL_URLS="https://www.youtube.com/@NateBJones/videos" python run_scheduled.py

    # Multiple channels (comma-separated)
    MONITOR_CHANNEL_URLS="https://www.youtube.com/@Channel1,https://www.youtube.com/@Channel2" python run_scheduled.py

    # Or set in .env file
    python run_scheduled.py
"""

import os
import sys

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from agent import run_agent
from observability import get_logger


def main():
    """Check all configured channels for new videos."""
    logger = get_logger()

    # Get channel URLs from environment
    channel_urls_str = os.environ.get("MONITOR_CHANNEL_URLS", "")

    if not channel_urls_str:
        print("Error: MONITOR_CHANNEL_URLS environment variable not set")
        print("Set it to a comma-separated list of YouTube channel URLs")
        sys.exit(1)

    # Parse channel URLs
    channel_urls = [url.strip() for url in channel_urls_str.split(",") if url.strip()]

    if not channel_urls:
        print("Error: No valid channel URLs found in MONITOR_CHANNEL_URLS")
        sys.exit(1)

    print(f"Checking {len(channel_urls)} channel(s) for new videos...")
    print("-" * 50)

    results = []

    for channel_url in channel_urls:
        print(f"\n--- Checking channel: {channel_url} ---")
        logger.info(f"Starting scheduled check for channel: {channel_url}")

        try:
            result = run_agent(channel_url)
            results.append({
                "channel_url": channel_url,
                "success": True,
                "result": result
            })
            print(result)
            logger.info(f"Completed check for channel: {channel_url}")

        except Exception as e:
            error_msg = str(e)
            results.append({
                "channel_url": channel_url,
                "success": False,
                "error": error_msg
            })
            print(f"Error checking channel: {error_msg}")
            logger.error(f"Error checking channel {channel_url}: {error_msg}")

    # Summary
    print("\n" + "=" * 50)
    print("SUMMARY")
    print("=" * 50)

    successful = sum(1 for r in results if r["success"])
    failed = len(results) - successful

    print(f"Channels checked: {len(results)}")
    print(f"Successful: {successful}")
    print(f"Failed: {failed}")

    if failed > 0:
        print("\nFailed channels:")
        for r in results:
            if not r["success"]:
                print(f"  - {r['channel_url']}: {r['error']}")

    # Exit with error code if any failures
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
