---
title: "Controller Loop"
tags: [concept, controller, cycle, autonomous]
created: "2026-04-13"
related:
  - "[[ShopAI Architecture]]"
  - "[[Brain]]"
  - "[[Reflection Hook]]"
  - "[[Adapter Hooks]]"
---

# Controller Loop

## Summary

`AutonomousController.run_cycle()` is the heartbeat of ShopAI. It
runs once per tick, walks through a fixed sequence of phases, and
either produces new actions or degrades gracefully. No phase may
raise — all failures are captured into `phase_errors`.

## Phases

```
data → analysis → brain → decisions → execution → reflection
```

| Phase | Produces |
|-------|----------|
| **data** | products, orders, customers, metrics pulled from Shopify |
| **analysis** | insights, anomalies, competitor snapshot |
| **brain** | top action + ranked candidates (see [[Brain]]) |
| **decisions** | proposed actions the brain committed to |
| **execution** | adapter side effects via [[Capability Routing]] |
| **reflection** | [[Reflection Hook|post-cycle pattern mining]] |

## Post-cycle side effects

After the reflection phase the controller calls:

1. `_log_cycle_to_vault` — writes a Win or Error note (see [[Obsidian Integration]])
2. `_log_decision_to_vault` — writes a Decision note for the top action
3. `run_post_cycle_hooks` — runs the [[Adapter Hooks|adapter-powered hooks]]

All three are wrapped so a failure never stops the next cycle.

## Guarantees

- **No-raise** — every phase is exception-swallowed
- **Bounded duration** — per-phase timeouts
- **Observable** — `cycle_result["phases"]` carries every phase's summary
- **Idempotent side effects** — Decision notes dedupe, vault writes are additive

## Related

- [[ShopAI Architecture]]
- [[Brain]]
- [[Reflection Hook]]
- [[Adapter Hooks]]
- [[Obsidian Integration]]
