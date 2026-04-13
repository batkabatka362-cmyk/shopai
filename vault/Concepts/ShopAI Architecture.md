---
title: "ShopAI Architecture"
tags: [concept, architecture, core]
created: "2026-04-13"
related:
  - "[[Adapter Pattern]]"
  - "[[Use Obsidian for Memory]]"
---

# ShopAI Architecture

## Summary

ShopAI is an autonomous e-commerce AI that manages Shopify stores. The architecture follows a brain-body model: the **core** (brain) thinks, decides, and learns; **adapters** (body) execute actions through external services.

## Core Systems

### Brain
- **DecisionBrain** - Makes decisions based on goals, context, and learned patterns
- **LearningLoop** - Captures outcomes and generates rules from patterns
- **GoalManager** - Tracks business goals and measures progress
- **ActionWeightStore** - Learns adapter success rates over time

### Memory
- **UnifiedMemory** - Single entry point for all memory operations
- **BrainMemory** - Working memory for current context
- [[Obsidian Integration]] - Knowledge base with graph visualization

### Controller
- **AutonomousController** - Orchestrates autonomous cycles
- Bootstraps 17+ adapter categories at startup
- Runs reflection hooks after each cycle

## Adapter Ecosystem

The [[Adapter Pattern]] connects ShopAI to 30+ external services:

| Category | Adapters |
|----------|----------|
| LLM | Groq, Gemini, DeepSeek, Mistral, Ollama, OpenRouter, HuggingFace, OpenAI, Anthropic |
| Email | Brevo, Resend, SendGrid, Klaviyo |
| SMS | Twilio |
| Payment | PayPal, Stripe |
| Ads | Google Ads, Meta Ads |
| Subscription | ReCharge |
| Vector DB | Weaviate, Pinecone |
| Search | Brave, Serper, DDGS |
| Voice | ElevenLabs |
| Automation | Zapier |
| Browser | Playwright |
| Scraper | Firecrawl |
| Reviews | Judge.me |
| Image | DALL-E 3 |

## Key Principle

> "Don't build new features. Find working apps/tools/AIs and connect them to ShopAI."

The core decides WHAT to do. The adapters execute it. No new business logic.

## Related

- [[Adapter Pattern]] - How adapters work
- [[Shopify API Basics]] - Primary platform
- [[Use Obsidian for Memory]] - Why we chose Obsidian
