#!/usr/bin/env python3
"""Bulk ingest existing notes into Supabase pgvector.

Reads markdown notes from a local directory and inserts them
into the Supabase documents table with embeddings.

Usage:
    python ingest_notes.py [notes_directory]
"""

import os
import sys

from dotenv import load_dotenv
load_dotenv()

from vector_store import ingest_document
from observability import get_logger


def ingest_notes_directory(directory: str) -> tuple[int, int]:
    """Ingest all markdown files from a directory.

    Returns:
        Tuple of (success_count, failure_count)
    """
    logger = get_logger()

    if not os.path.isdir(directory):
        logger.error(f"Directory not found: {directory}")
        return 0, 0

    md_files = sorted(f for f in os.listdir(directory) if f.endswith(".md"))

    if not md_files:
        logger.info(f"No markdown files found in {directory}")
        return 0, 0

    print(f"Found {len(md_files)} markdown files in {directory}")

    success = 0
    failed = 0

    for filename in md_files:
        filepath = os.path.join(directory, filename)

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()

            if not content.strip():
                print(f"  Skipping empty file: {filename}")
                continue

            # Extract title from first heading if present
            title = filename
            for line in content.split("\n"):
                if line.startswith("# "):
                    title = line[2:].strip()
                    break

            print(f"  Ingesting: {filename} ({len(content)} chars)")

            if ingest_document(content, filepath, metadata={"title": title, "filename": filename}):
                success += 1
            else:
                failed += 1

        except Exception as e:
            print(f"  Error reading {filename}: {e}")
            failed += 1

    return success, failed


def main():
    directory = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("NOTES_LOCAL_DIR", "./notes")

    print(f"Ingesting notes from: {directory}")
    print(f"Supabase URL: {os.environ.get('SUPABASE_URL', 'NOT SET')}")
    print()

    success, failed = ingest_notes_directory(directory)

    print(f"\nDone: {success} ingested, {failed} failed")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
