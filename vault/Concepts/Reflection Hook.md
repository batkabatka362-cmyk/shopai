---
title: "Reflection Hook"
tags: [concept, reflection, learning, patterns]
created: "2026-04-13"
related:
  - "[[Controller Loop]]"
  - "[[Brain]]"
  - "[[Memory]]"
---

# Reflection Hook

## Summary

At the tail of every cycle, the controller runs `_run_reflection_hook`
which mines the cycle's error ledger and action outcomes for
repeating patterns. High-confidence patterns are promoted to
**SOFT rules** on the [[Brain]]; with enough supporting evidence
they graduate to **HARD rules**.

## What it does

1. Walk `cycle_result["phase_errors"]` and the action outcomes
2. Cluster similar errors (regex-normalised signatures)
3. If a signature has crossed the support + confidence threshold,
   promote it to a rule
4. If `OBSIDIAN_VAULT_PATH` is set, auto-export the promoted
   patterns via [[Memory|`VaultMemoryBridge.export_knowledge()`]]
   → `vault/ShopAI/Learned/`
5. Stash a reflection summary on `cycle_result["reflection"]`
   so [[Obsidian Integration|Win notes]] can record it

## Promotion rules

| Signal | Threshold | Effect |
|--------|-----------|--------|
| Same error across N cycles | 3× | Create SOFT rule |
| Same action succeeds N times | 5× | Increase `ActionWeight` |
| SOFT rule survives N cycles | 10× | Promote to HARD |

## Best-effort

Like every post-cycle side effect, reflection is wrapped in a
broad `try/except`. A vault write failure never blocks the next
cycle. See [[Best-Effort Adapter Hooks]] for the philosophy.

## Related

- [[Controller Loop]] — caller
- [[Brain]] — target of rule promotions
- [[Memory]] — pattern storage + vault export
- [[Obsidian Integration]] — where Learned/ notes land
