-- Supabase pgvector schema for YouTube Analyzer RAG chatbot
-- Run this in the Supabase SQL editor to set up the vector store.

create extension if not exists vector;

create table documents (
  id bigserial primary key,
  content text not null,
  embedding vector(1536),
  source_uri text,
  metadata jsonb default '{}',
  created_at timestamptz default now()
);

create index on documents using ivfflat (embedding vector_cosine_ops) with (lists = 100);

-- search_path is pinned explicitly. Without it the function resolves unqualified
-- names using the caller's search_path, so a caller who can create objects in an
-- earlier schema could shadow `documents` or the vector operators and change what
-- this function does. Flagged by Supabase's database linter as
-- function_search_path_mutable (0011).
create or replace function match_documents(
  query_embedding vector(1536),
  match_count int default 5,
  match_threshold float default 0.5
) returns table (id bigint, content text, source_uri text, metadata jsonb, similarity float)
language plpgsql
set search_path = public, pg_temp
as $$
begin
  return query
  select d.id, d.content, d.source_uri, d.metadata,
         1 - (d.embedding <=> query_embedding) as similarity
  from public.documents d
  where 1 - (d.embedding <=> query_embedding) > match_threshold
  order by d.embedding <=> query_embedding
  limit match_count;
end;
$$;

-- Note on RLS: `documents` has RLS enabled with no policies, which is the correct
-- posture here — all access goes through the service role key, which bypasses RLS,
-- so anon/authenticated callers are denied by default. Supabase's linter reports
-- this as INFO (rls_enabled_no_policy); do not "fix" it by adding a permissive
-- policy, which would expose every summary to the public anon key.
