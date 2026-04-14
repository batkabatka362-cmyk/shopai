---
title: "Example Learned Pattern"
source: "shopai"
tags: [shopai, learned, example, pattern]
confidence: 0.78
exported_at: "2026-04-14T00:00:00+00:00"
related:
  - "[[Reflection Hook]]"
  - "[[Memory]]"
  - "[[00 Home]]"
---

# Example Learned Pattern

> **Seed note.** This file ships in the repo so the
> [[Graph View Tips|graph view]] shows an orange cluster on first
> open. Real auto-exported notes overwrite this pattern once
> ShopAI promotes its first reflection result.

## What this demonstrates

The controller's reflection hook promoted a pattern named
`openai/chat_complete intermittent 429s` after seeing it N times
across cycles. The promotion triggers
`VaultMemoryBridge.export_knowledge()`, which writes a note like
this one into `ShopAI/Learned/`.

## Shape of a real entry

```yaml
title: "<adapter>/<capability> <symptom>"
source: "shopai"
confidence: 0.0 – 1.0
exported_at: ISO-8601 UTC
```

The body contains the pattern's evidence: representative error
messages, the burst rate the [[Cost Forecast]] module observed, and
whether the [[Learned Route Weights]] ledger penalised the pair.

## Why orange

`.obsidian/graph.json` maps `path:ShopAI/Learned` to RGB #ffa500.
The colour exists so you can instantly distinguish what ShopAI
*learned on its own* (orange) from what you *wrote manually*
(blue/teal/red/green/purple).

## Related

- [[Reflection Hook]] — where promotion happens
- [[Memory]] — where the record lives before export
- [[Learned Route Weights]] — how promoted patterns feed routing
- [[Cost Forecast]] — trajectory spike detection
- [[00 Home]]
