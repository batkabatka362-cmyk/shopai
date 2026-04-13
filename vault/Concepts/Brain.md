---
title: "Brain"
tags: [concept, brain, decisions, learning]
created: "2026-04-13"
related:
  - "[[ShopAI Architecture]]"
  - "[[Memory]]"
  - "[[Reflection Hook]]"
  - "[[Capability Routing]]"
---

# Brain

## Summary

The **brain** is ShopAI's cognitive layer. It decides *what* to do
each cycle, learns from outcomes, and nudges future decisions toward
actions that historically succeed. The body ([[Adapter Pattern|adapters]])
executes; the brain never calls a vendor API directly.

## Components

### DecisionBrain
- Takes goals, current context, and past patterns
- Produces a ranked list of candidate actions
- Top action flows into the `decisions` phase of the cycle

### LearningLoop
- Watches outcomes of every executed action
- Mines repeated success/failure patterns
- Promotes high-confidence patterns to SOFT rules (then HARD after more evidence)

### GoalManager
- Tracks business goals (revenue, conversions, retention)
- Measures progress, flags regressions
- Rewrites goal weights based on what's moving

### ActionWeightStore
- Per-adapter success/failure counter, Bayesian-smoothed
- Informs `Capability Routing` — high-weight adapters are preferred

## Lifecycle

```
Goals + Context + Memory
        ↓
   DecisionBrain
        ↓
  Candidate actions (ranked)
        ↓
   SmartRouter → Adapter.execute()
        ↓
      Outcome
        ↓
   LearningLoop → ActionWeightStore + patterns → [[Memory]]
```

## Related

- [[ShopAI Architecture]]
- [[Memory]] — where patterns are stored
- [[Reflection Hook]] — end-of-cycle pattern promotion
- [[Controller Loop]] — orchestrator
- [[Capability Routing]] — decision → execution bridge
