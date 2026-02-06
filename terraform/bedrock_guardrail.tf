# Bedrock Guardrail for RAG Chatbot - content filtering and topic control
# Conditional on enable_knowledge_base (chatbot requires KB)

resource "aws_bedrock_guardrail" "chatbot" {
  count = var.enable_knowledge_base ? 1 : 0
  name  = "${var.project_name}-chatbot-guardrail"

  blocked_input_messaging   = "I can't process that request. Please ask questions about YouTube video summaries."
  blocked_outputs_messaging = "I can't provide that response. Please ask questions about YouTube video summaries."

  # Content filters - all at HIGH threshold
  content_policy_config {
    filters_config {
      type            = "HATE"
      input_strength  = "HIGH"
      output_strength = "HIGH"
    }
    filters_config {
      type            = "INSULTS"
      input_strength  = "HIGH"
      output_strength = "HIGH"
    }
    filters_config {
      type            = "SEXUAL"
      input_strength  = "HIGH"
      output_strength = "HIGH"
    }
    filters_config {
      type            = "VIOLENCE"
      input_strength  = "HIGH"
      output_strength = "HIGH"
    }
    filters_config {
      type            = "MISCONDUCT"
      input_strength  = "HIGH"
      output_strength = "HIGH"
    }
    filters_config {
      # PROMPT_ATTACK: output strength MUST be NONE per AWS requirement
      type            = "PROMPT_ATTACK"
      input_strength  = "HIGH"
      output_strength = "NONE"
    }
  }

  # Topic policy - deny off-topic questions
  topic_policy_config {
    topics_config {
      name       = "off-topic"
      type       = "DENY"
      definition = "Questions or requests that are not related to YouTube video analysis, summaries, or content from analyzed videos."
      examples = [
        "Write me a poem about cats",
        "What is the capital of France",
        "Help me write code for a web app",
        "Tell me a joke",
      ]
    }
  }

  # Word policy - block profanity
  word_policy_config {
    managed_word_lists_config {
      type = "PROFANITY"
    }
  }
}

# Published version (Converse API requires numeric version, not "DRAFT")
resource "aws_bedrock_guardrail_version" "chatbot" {
  count         = var.enable_knowledge_base ? 1 : 0
  guardrail_arn = aws_bedrock_guardrail.chatbot[0].guardrail_arn
  description   = "Initial version"
}
