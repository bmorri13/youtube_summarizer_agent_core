"""Vector store operations using Supabase pgvector + OpenAI embeddings."""

import os

from openai import OpenAI
from supabase import create_client

from observability import get_logger

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_DIMENSIONS = 1536

# Lazy-initialized clients
_openai_client = None
_supabase_client = None


def _get_openai_client():
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI()
    return _openai_client


def _get_supabase_client():
    global _supabase_client
    if _supabase_client is None:
        if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
            raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
        _supabase_client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    return _supabase_client


def get_embedding(text: str) -> list[float]:
    """Generate embedding for text using OpenAI API."""
    client = _get_openai_client()
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text,
    )
    return response.data[0].embedding


def retrieve_similar_documents(query: str, max_results: int = 5, match_threshold: float = 0.5) -> list[dict]:
    """Retrieve similar documents from Supabase pgvector.

    Returns list of dicts with keys: text, score, source_uri
    """
    logger = get_logger()

    try:
        embedding = get_embedding(query)
        supabase = _get_supabase_client()

        response = supabase.rpc("match_documents", {
            "query_embedding": embedding,
            "match_count": max_results,
            "match_threshold": match_threshold,
        }).execute()

        results = []
        for row in response.data or []:
            results.append({
                "text": row["content"],
                "score": row["similarity"],
                "source_uri": row.get("source_uri", ""),
            })

        return results
    except Exception as e:
        logger.error(f"Vector retrieval error: {e}")
        return []


def ingest_document(content: str, source_uri: str, metadata: dict = None) -> bool:
    """Embed and insert a document into Supabase pgvector.

    Args:
        content: Document text content
        source_uri: Source path/URI for the document
        metadata: Optional metadata dict

    Returns:
        True if successful, False otherwise
    """
    logger = get_logger()

    try:
        embedding = get_embedding(content)
        supabase = _get_supabase_client()

        supabase.table("documents").insert({
            "content": content,
            "embedding": embedding,
            "source_uri": source_uri,
            "metadata": metadata or {},
        }).execute()

        logger.info(f"Ingested document: {source_uri}")
        return True
    except Exception as e:
        logger.error(f"Vector ingestion error for {source_uri}: {e}")
        return False
