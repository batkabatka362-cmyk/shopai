---
title: "Feedback Learner"
tags: [concept, feedback, learning, reflection]
created: "2026-04-14"
related:
  - "[[Reflection Hook]]"
  - "[[Memory]]"
  - "[[Controller Loop]]"
---

# Feedback Learner

## Summary

A second-order learning path: the dashboard's chat-feedback
handler writes operator down-rates to `vault/ShopAI/Feedback/`,
and this module promotes recurring complaint themes into lesson
notes stored under `vault/ShopAI/Learned/lessons/`. On the next
cycle, the brain pulls those lessons into its context so the
behaviour that triggered the complaint doesn't repeat.

## Why it exists separate from reflection

The [[Reflection Hook]] mines *errors and outcomes* — things the
system sees internally. The feedback learner mines *operator
corrections* — things only humans know. They feed the same
memory store but through different intake paths.

## How it works

1. **Scan** — `learn_from_feedback(vault_path)` reads every
   note in `ShopAI/Feedback/` that has `tag: down`.
2. **Cluster** — word-frequency clustering groups complaints
   with shared vocabulary into themes.
3. **Threshold** — themes below the minimum-support floor are
   discarded as one-offs.
4. **Write** — each remaining theme becomes a lesson note in
   `ShopAI/Learned/lessons/<theme>.md`, with wikilinks back to
   the source complaints.
5. **Recall** — on the next cycle, the brain's context loader
   pulls the newest lessons and prepends them to the system
   prompt.

## Best-effort contract

Like every vault integration, this module never blocks a cycle.
A missing `vault/` directory, unreadable note, or write failure
is logged at DEBUG and swallowed — the autonomous loop rolls on.

## Related

- [[Reflection Hook]]
- [[Memory]]
- [[Controller Loop]]
