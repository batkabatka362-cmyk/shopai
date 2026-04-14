---
title: "How Auto-Export Works"
source: "shopai"
tags: [shopai, learned, documentation, meta]
exported_at: "2026-04-14T00:00:00+00:00"
related:
  - "[[Reflection Hook]]"
  - "[[Memory]]"
  - "[[Graph View Tips]]"
  - "[[00 Home]]"
---

# How Auto-Export Works

> Seed note. Explains the round-trip between the autonomous
> controller and this folder so operators know what they're
> looking at when new orange nodes appear.

## The loop

```
run_cycle()
   ↓
_run_reflection_hook() — mines error patterns
   ↓ promotes N patterns
_maybe_export_to_vault(report)
   ↓ (when promoted > 0  OR  hourly sweep is due)
VaultMemoryBridge.export_knowledge(UnifiedMemory)
   ↓ writes one .md per memory record with source="learned"
ShopAI/Learned/<sanitized-title>.md
```

## Rate limiting

Two triggers make an export run:

1. **Promotion** — the reflection cycle confirmed at least one
   new SOFT rule.
2. **Hourly sweep** — more than an hour elapsed since the last
   export, regardless of promotion. This catches memory records
   written by out-of-band paths ([[Feedback Learner]], manual
   ingests, external agents) that the promotion gate would miss.

## Idempotency

`export_knowledge` checks `target.exists()` before writing, so an
existing note with the same sanitised title is left alone. Edit
notes freely — ShopAI won't overwrite your changes.

## Boot import

On controller `initialize()`, `_maybe_import_vault_on_boot()`
scans the entire vault and ingests every `.md` into
[[Memory|UnifiedMemory]] with category `vault_note`. This means
notes you wrote by hand are searchable by the brain on the very
first cycle.

## Related

- [[Reflection Hook]]
- [[Memory]]
- [[Graph View Tips]]
- [[Learned Route Weights]]
- [[00 Home]]
