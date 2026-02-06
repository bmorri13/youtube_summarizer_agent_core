# Bedrock Knowledge Base with S3 Vectors for semantic search over video notes
# Requires AWS provider >= 6.24.0 for S3 Vectors support

# S3 Vector Bucket (stores vector embeddings)
resource "aws_s3vectors_vector_bucket" "notes_vectors" {
  count              = var.enable_knowledge_base ? 1 : 0
  vector_bucket_name = "${var.project_name}-vectors-${random_id.bucket_suffix.hex}"
}

# S3 Vector Index (defines embedding dimensions and distance metric)
resource "aws_s3vectors_index" "notes_index" {
  count              = var.enable_knowledge_base ? 1 : 0
  vector_bucket_name = aws_s3vectors_vector_bucket.notes_vectors[0].vector_bucket_name
  index_name         = "notes-index"

  # Titan Embed Text v2 uses 1024 dimensions
  data_type = "float32"
  dimension = 1024

  # Cosine similarity for semantic search
  distance_metric = "cosine"

  # Move Bedrock metadata to non-filterable storage (40KB limit vs 2KB filterable limit)
  # This prevents "Filterable metadata must have at most 2048 bytes" errors
  metadata_configuration {
    non_filterable_metadata_keys = [
      "AMAZON_BEDROCK_TEXT",
      "AMAZON_BEDROCK_METADATA"
    ]
  }
}

# IAM Role for Bedrock Knowledge Base
resource "aws_iam_role" "bedrock_kb" {
  count = var.enable_knowledge_base ? 1 : 0
  name  = "${var.project_name}-bedrock-kb-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "bedrock.amazonaws.com"
      }
      Action = "sts:AssumeRole"
      Condition = {
        StringEquals = {
          "aws:SourceAccount" = data.aws_caller_identity.current.account_id
        }
      }
    }]
  })
}

# IAM Policy - S3 Data Source Access (read notes bucket)
resource "aws_iam_role_policy" "bedrock_kb_s3" {
  count = var.enable_knowledge_base ? 1 : 0
  name  = "s3-data-source-access"
  role  = aws_iam_role.bedrock_kb[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "s3:GetObject",
        "s3:ListBucket"
      ]
      Resource = [
        aws_s3_bucket.notes.arn,
        "${aws_s3_bucket.notes.arn}/notes/*"
      ]
    }]
  })
}

# IAM Policy - Bedrock Model Invocation (for embeddings)
resource "aws_iam_role_policy" "bedrock_kb_model" {
  count = var.enable_knowledge_base ? 1 : 0
  name  = "bedrock-model-invocation"
  role  = aws_iam_role.bedrock_kb[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["bedrock:InvokeModel"]
      Resource = ["arn:aws:bedrock:${var.aws_region}::foundation-model/${var.kb_embedding_model}"]
    }]
  })
}

# IAM Policy - S3 Vectors Access (read/write vector embeddings)
resource "aws_iam_role_policy" "bedrock_kb_vectors" {
  count = var.enable_knowledge_base ? 1 : 0
  name  = "s3-vectors-access"
  role  = aws_iam_role.bedrock_kb[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "s3vectors:CreateIndex",
        "s3vectors:DeleteIndex",
        "s3vectors:DescribeIndex",
        "s3vectors:PutVectors",
        "s3vectors:DeleteVectors",
        "s3vectors:QueryVectors",
        "s3vectors:GetVectors"
      ]
      Resource = [
        aws_s3vectors_vector_bucket.notes_vectors[0].vector_bucket_arn,
        "${aws_s3vectors_vector_bucket.notes_vectors[0].vector_bucket_arn}/*"
      ]
    }]
  })
}

# Bedrock Knowledge Base
resource "aws_bedrockagent_knowledge_base" "notes" {
  count    = var.enable_knowledge_base ? 1 : 0
  name     = "${var.project_name}-knowledge-base"
  role_arn = aws_iam_role.bedrock_kb[0].arn

  knowledge_base_configuration {
    type = "VECTOR"
    vector_knowledge_base_configuration {
      embedding_model_arn = "arn:aws:bedrock:${var.aws_region}::foundation-model/${var.kb_embedding_model}"
    }
  }

  storage_configuration {
    type = "S3_VECTORS"
    s3_vectors_configuration {
      index_arn = aws_s3vectors_index.notes_index[0].index_arn
    }
  }

  depends_on = [
    aws_iam_role_policy.bedrock_kb_s3,
    aws_iam_role_policy.bedrock_kb_model,
    aws_iam_role_policy.bedrock_kb_vectors
  ]
}

# Bedrock Data Source (S3 bucket with notes)
resource "aws_bedrockagent_data_source" "notes_s3" {
  count             = var.enable_knowledge_base ? 1 : 0
  name              = "notes-s3-data-source"
  knowledge_base_id = aws_bedrockagent_knowledge_base.notes[0].id

  data_source_configuration {
    type = "S3"
    s3_configuration {
      bucket_arn         = aws_s3_bucket.notes.arn
      inclusion_prefixes = ["notes/"]
    }
  }

  # Chunking configuration for markdown notes
  vector_ingestion_configuration {
    chunking_configuration {
      chunking_strategy = "FIXED_SIZE"
      fixed_size_chunking_configuration {
        max_tokens         = 512
        overlap_percentage = 20
      }
    }
  }
}
