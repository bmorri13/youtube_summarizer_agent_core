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

create or replace function match_documents(
  query_embedding vector(1536),
  match_count int default 5,
  match_threshold float default 0.5
) returns table (id bigint, content text, source_uri text, metadata jsonb, similarity float)
language plpgsql as $$
begin
  return query
  select d.id, d.content, d.source_uri, d.metadata,
         1 - (d.embedding <=> query_embedding) as similarity
  from documents d
  where 1 - (d.embedding <=> query_embedding) > match_threshold
  order by d.embedding <=> query_embedding
  limit match_count;
end;
$$;
