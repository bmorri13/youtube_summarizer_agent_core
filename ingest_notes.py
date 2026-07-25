#!/usr/bin/env python3
"""Bulk ingest existing notes into Supabase pgvector.

Reads markdown notes from a local directory and inserts them
into the Supabase documents table with embeddings.

Notes already present in the documents table are skipped, so this is safe to
re-run — it ingests only the gap. Pass --force to ingest everything regardless
(this will create duplicate rows).

Usage:
    python ingest_notes.py [notes_directory] [--force] [--dry-run]
"""

import os
import sys

from dotenv import load_dotenv
load_dotenv()

from vector_store import ingest_document, list_ingested_source_uris
from observability import get_logger


def ingest_notes_directory(directory: str, force: bool = False, dry_run: bool = False) -> tuple[int, int]:
    """Ingest markdown files from a directory, skipping those already ingested.

    Args:
        directory: Directory containing .md notes
        force: Ingest every file even if already present (creates duplicates)
        dry_run: Report what would be ingested without writing

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

    # Skip anything already in the table. Compared by basename so a note ingested
    # under a different absolute path (e.g. /app/notes vs ./notes) still matches.
    if force:
        print("--force: skipping the already-ingested check (may create duplicates)")
        already = set()
    else:
        try:
            already = {os.path.basename(uri) for uri in list_ingested_source_uris()}
            print(f"Already in vector store: {len(already)}")
        except Exception as e:
            logger.error(f"Could not read existing documents, aborting to avoid duplicates: {e}")
            return 0, 0

    pending = [f for f in md_files if f not in already]
    skipped = len(md_files) - len(pending)
    if skipped:
        print(f"Skipping {skipped} already-ingested file(s)")
    print(f"To ingest: {len(pending)}")

    if dry_run:
        for filename in pending:
            print(f"  [dry-run] would ingest: {filename}")
        return 0, 0

    success = 0
    failed = 0

    for filename in pending:
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
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    flags = {a for a in sys.argv[1:] if a.startswith("-")}

    directory = args[0] if args else os.environ.get("NOTES_LOCAL_DIR", "./notes")

    print(f"Ingesting notes from: {directory}")
    print(f"Supabase URL: {os.environ.get('SUPABASE_URL', 'NOT SET')}")
    print()

    success, failed = ingest_notes_directory(
        directory,
        force="--force" in flags,
        dry_run="--dry-run" in flags,
    )

    print(f"\nDone: {success} ingested, {failed} failed")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
