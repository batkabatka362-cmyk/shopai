"""LLM adapters.

Importing this package does NOT register any adapter — concrete
adapters are imported lazily by the consumer (or by
``core/adapters/llm/bootstrap.py``) so test isolation stays
clean. To register every available LLM adapter at startup,
call::

    from core.adapters.llm import bootstrap
    bootstrap.register_all()

The available adapters mirror the multi-provider strategy:

  * groq        — primary chat, 300 tok/sec, free tier 14400/day
  * gemini      — long context (1M), multimodal
  * deepseek    — code generation + deep reasoning
  * mistral     — EU-resident, GDPR sovereign
  * ollama      — local self-hosted, PII-safe, $0 cost
  * openrouter  — fallback router, 100+ models
  * huggingface — embeddings + specialized model inference
"""
from ._base import LLMBaseAdapter
from ._openai_compat import OpenAICompatAdapter

__all__ = ["LLMBaseAdapter", "OpenAICompatAdapter"]
