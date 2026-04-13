---
title: "Capability Routing"
tags: [concept, router, adapters, dispatch]
created: "2026-04-13"
related:
  - "[[Adapter Pattern]]"
  - "[[Brain]]"
  - "[[_Capabilities MOC]]"
  - "[[_Adapters Catalog]]"
---

# Capability Routing

## Summary

`SmartRouter` is the dispatch layer between the [[Brain|brain's]]
intent (a `Capability`) and a concrete adapter that can satisfy it.
It turns "send an email" into "use Resend because it's configured,
healthy, and the highest-priority email adapter we know."

## Selection algorithm

```
SmartRouter.execute(capability, params):
  1. candidates = all adapters that declare `capability`
  2. candidates = filter(is_configured())
  3. sort by (action_weight × priority) descending
  4. for each candidate:
       try adapter._execute(capability, params)
       if ok: return result
       else: log, try next
  5. return AdapterResult(ok=False, reason="no_adapter")
```

## Why this matters

- **No vendor lock-in** — adding `PostHog` doesn't mean losing `Mixpanel`;
  the router decides per-call.
- **Self-healing** — a flaky vendor gets demoted by `ActionWeightStore`
  so the router naturally routes away.
- **Opt-in by credentials** — operators just set `HUBSPOT_API_KEY`
  and the CRM hook starts firing. No config flag needed.
- **Graceful empty** — an unknown capability returns
  `ok=False, reason="no_adapter"` rather than raising.

## Capability scope

The enum is defined in `core/adapters/base.py` and grouped by
concern — see [[_Capabilities MOC]] for every value.

## Related

- [[Adapter Pattern]] — the interface the router dispatches against
- [[Brain]] — source of capability requests
- [[Adapter Hooks]] — primary consumer in the autonomous cycle
- [[_Adapters Catalog]] — every adapter available to the router
