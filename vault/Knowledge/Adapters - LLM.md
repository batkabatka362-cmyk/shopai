---
title: "Adapters - LLM"
tags: [knowledge, adapters, llm]
created: "2026-04-13"
related:
  - "[[_Adapters Catalog]]"
  - "[[_Capabilities MOC]]"
  - "[[Brain]]"
---

# Adapters - LLM

## Summary

LLM adapters power the [[Brain|brain]]'s reasoning step and any
language-model task (drafting, classification, summarisation).
With nine vendors in play, the router can fall back across
providers when one is rate-limited or down.

## Adapters

| Adapter | Priority | Auth | Notes |
|---------|----------|------|-------|
| **Anthropic** | 95 | `ANTHROPIC_API_KEY` | Deep-think default |
| **OpenAI** | 90 | `OPENAI_API_KEY` | Tools + embeddings |
| **Groq** | 85 | `GROQ_API_KEY` | Fastest; preferred for cheap/quick calls |
| **Gemini** | 80 | `GOOGLE_API_KEY` | Long context |
| **DeepSeek** | 75 | `DEEPSEEK_API_KEY` | Budget reasoning |
| **Mistral** | 70 | `MISTRAL_API_KEY` | EU hosting |
| **OpenRouter** | 60 | `OPENROUTER_API_KEY` | Meta-router |
| **HuggingFace** | 50 | `HF_TOKEN` | Experimentation |
| **Ollama** | 40 | none | Local fallback |

## Capabilities

- `LLM_COMPLETE` — single-turn completion
- `LLM_CHAT` — multi-turn chat
- `LLM_EMBED` — embeddings (vector representation)

## Cost-aware routing

Every LLM adapter exposes `cost_per_call` and an `estimate_cost()`
helper so the brain can route expensive reasoning to Anthropic and
cheap classification to Groq.

## Related

- [[Brain]] — primary caller
- [[Capability Routing]] — router picks by priority + weight
- [[_Capabilities MOC]]
