---
title: "_Concepts MOC"
tags: [moc, concepts, index]
created: "2026-04-13"
aliases: ["Concepts Map", "Concepts Index"]
related:
  - "[[00 Home]]"
  - "[[ShopAI Architecture]]"
---

# _Concepts MOC

> Index for every core concept in ShopAI. Each concept is a node in
> the graph; together they form the mental model behind the system.

## Top-level

- [[ShopAI Architecture]] — the root diagram
- [[Adapter Pattern]] — how vendors plug in

## Cognition

- [[Brain]] — `DecisionBrain`, `LearningLoop`, `GoalManager`
- [[Memory]] — `UnifiedMemory` and its layers
- [[Reflection Hook]] — post-tick pattern mining

## Execution

- [[Controller Loop]] — the autonomous cycle phases
- [[Capability Routing]] — `SmartRouter` selection logic
- [[Adapter Hooks]] — per-cycle side effects

## Principles

- Adapters > features — connect, don't rebuild
- Best-effort hooks — a side-effect failure never fails the cycle
- Capability-first — the brain requests capabilities, not vendors
- Graceful degradation — unconfigured adapters register as no-ops

## See also

- [[_Adapters Catalog]] — every concrete adapter
- [[_Capabilities MOC]] — every capability, grouped by concern
- [[00 Home]]
