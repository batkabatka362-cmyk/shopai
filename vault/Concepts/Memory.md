---
title: "Memory"
tags: [concept, memory, architecture]
created: "2026-04-13"
related:
  - "[[ShopAI Architecture]]"
  - "[[Brain]]"
  - "[[Obsidian Integration]]"
---

# Memory

## Summary

`UnifiedMemory` is the single entry point for every memory read and
write in ShopAI. Underneath it layers several stores so the [[Brain]]
gets consistent context regardless of where a fact actually lives.

## Layers

| Layer | Purpose | Backing |
|-------|---------|---------|
| **BrainMemory** | Current cycle working memory | In-process dict |
| **PatternStore** | Learned success/failure patterns | SQLite |
| **VectorStore** | Semantic recall across notes & outcomes | Weaviate or Pinecone |
| **VaultBridge** | Operator-visible knowledge base | Obsidian vault on disk |

`UnifiedMemory.retrieve(query, context)` fans out to all layers and
merges results; `vault_knowledge` key in the result comes from
[[Obsidian Integration|the vault bridge]].

## VaultMemoryBridge

Two directions:

- **import_vault()** — walks the vault, classifies notes with the
  quality engine, ingests high-quality content as patterns.
- **export_knowledge()** — writes promoted patterns from memory back
  to `ShopAI/Learned/` so operators see what the system has learned.

Both are idempotent. Import tracks state in
`.shopai_import_state.json`; export skips files that already exist.

## Design principles

- Operator-visible — every long-lived memory has a markdown face
- Idempotent — re-runs never double-write
- Layered, not siloed — retrieve hits all stores, brain doesn't care
- Gracefully empty — missing vault, missing vector DB → memory still works

## Related

- [[ShopAI Architecture]]
- [[Brain]] — primary consumer
- [[Reflection Hook]] — primary writer
- [[Obsidian Integration]] — vault side
