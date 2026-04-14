---
title: "Learned Route Weights"
tags: [concept, routing, reflection, learning, adapter]
created: "2026-04-14"
related:
  - "[[Reflection Hook]]"
  - "[[Capability Routing]]"
  - "[[Adapter Hooks]]"
  - "[[Memory]]"
---

# Learned Route Weights

## Summary

A per-`(adapter, capability)` weight table that closes the loop
between the [[Reflection Hook]] and [[Capability Routing|the
smart router]]. When reflection promotes an error pattern that
names both adapter and capability, the router penalises that pair
on subsequent calls — without waiting for the breaker to trip.

## Why this exists

The router already blends declared priority, preference, cost,
and composite health. What it could not do before this module
was learn from reflection's own output: a promoted SOFT rule
like *"openai/chat_complete fails intermittently"* changed
nothing about the next routing decision. The weight ledger
translates that promotion into an arithmetic penalty on the
next score computation.

## How it works

```
reflection promotes pattern → apply_reflection_report()
                                 ↓
                            penalize(adapter, capability, 0.5)
                                 ↓
                            weight multiplies, clamped to [0.05, 1.0]
                                 ↓
router._candidates:  score -= (1 - weight) * priority
                                 ↓
                            penalised adapter ranks lower
```

## Design rules

- **Clamped, decaying, never deleted.** Weights recover toward
  1.0 over a configurable half-life (default 6 hours) so a
  one-off outage self-heals.
- **Additive, not multiplicative.** Multiplying a *negative*
  score by a weight < 1 would flip the penalty's sign (which
  was a real bug caught in the first self-critique pass).
  Additive subtraction proportional to the adapter's declared
  priority is monotone in every sign regime.
- **LRU bounded.** A process-wide cap (`max_rows=2048`) with
  OrderedDict.move_to_end on each touch; oldest untouched rows
  evict first, so a runaway feeder can't starve fresh signals.

## Related

- [[Reflection Hook]]
- [[Capability Routing]]
- [[Adapter Hooks]]
- [[Memory]]
