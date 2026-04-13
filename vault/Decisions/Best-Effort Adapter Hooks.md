---
title: "Best-Effort Adapter Hooks"
tags: [decision, architecture, reliability, adr]
created: "2026-04-13"
status: "accepted"
outcome: "successful"
related:
  - "[[Adapter Hooks]]"
  - "[[Controller Loop]]"
  - "[[Reflection Hook]]"
---

# Best-Effort Adapter Hooks

## Context

Per-cycle side effects — analytics events, CRM upserts, helpdesk
tickets, automation webhooks — need to happen *after* the cycle
completes. A simple inline call chain works, but any single
failure (vendor rate-limited, config missing, network blip) would
fail the whole cycle. That's unacceptable for an autonomous loop.

## Options considered

1. **Inline, fail-loud** — simple, but one bad vendor kills the cycle
2. **Queue + async worker** — robust, but adds infrastructure, state,
   and debugging complexity
3. **Best-effort + structured summary** — wrap every hook in
   `try/except`, record `ok / adapter / reason` per hook on
   `cycle_result["phases"]["adapter_hooks"]`

## Decision

**Option 3.** The hooks module (`adapter_hooks.py`) wraps every
adapter call in `_safe_route_execute` and every hook itself in
another `try/except`. A hook failure degrades gracefully:

- The cycle keeps going
- Operators see *what* failed in the cycle summary
- `ActionWeightStore` gets the signal to downweight the failing
  adapter

## Consequences

- **Pro** — operators configure whatever vendors they want; missing
  config is silent, not fatal
- **Pro** — a single flaky vendor doesn't cascade
- **Con** — silent failures can mask real problems → mitigated by
  the structured summary and helpdesk escalation above threshold
- **Kill-switch** — `SHOPAI_ADAPTER_HOOKS=off` for paranoid
  deployments

## Related

- [[Adapter Hooks]] — the implementation
- [[Controller Loop]] — caller
- [[Reflection Hook]] — same best-effort philosophy applied
