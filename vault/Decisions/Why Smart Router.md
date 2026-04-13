---
title: "Why Smart Router"
tags: [decision, architecture, router, adr]
created: "2026-04-13"
status: "accepted"
outcome: "successful"
related:
  - "[[Capability Routing]]"
  - "[[Adapter Pattern]]"
---

# Why Smart Router

## Context

Each adapter category has multiple vendors (5 search engines, 9
LLMs, 3 helpdesks, 6 email providers). Without a routing layer
every caller would either hard-code a vendor or reimplement
fallback logic.

## Options considered

1. **Hard-code a primary per category** — simplest. But adding a
   new vendor means editing every call-site.
2. **Dependency injection (pass adapter as arg)** — cleaner code,
   but punts the "which vendor?" decision to every caller.
3. **Smart router keyed on `Capability` enum** — callers ask for
   a capability, the router picks the best-configured adapter by
   priority + observed weight.

## Decision

**Option 3.** See [[Capability Routing]] for the algorithm.

Three payoffs made it worth the upfront investment:

- **Zero-touch vendor add** — a new vendor registers itself on
  import; every capability it declares is automatically routable.
- **Self-healing** — `ActionWeightStore` demotes flaky vendors
  without any code change.
- **Credential-only opt-in** — operators configure `OPENAI_API_KEY`
  and the router starts using OpenAI. No flag, no re-deploy.

## Consequences

- Small runtime overhead (one dict lookup per call)
- Tests need to stub the router (see [[Pytest Patterns]])
- Router misconfiguration is visible — missing adapter returns
  `AdapterResult(ok=False, reason="no_adapter")`, caller handles

## Related

- [[Capability Routing]]
- [[Adapter Pattern]]
- [[Adapter Hooks]] — primary beneficiary
