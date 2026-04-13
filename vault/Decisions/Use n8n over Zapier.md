---
title: "Use n8n over Zapier"
tags: [decision, automation, adapter, adr]
created: "2026-04-13"
status: "accepted"
outcome: "successful"
related:
  - "[[Adapters - Automation]]"
  - "[[Adapter Hooks]]"
---

# Use n8n over Zapier

## Context

ShopAI needs to POST cycle summaries to an automation platform so
operators can fan out to Slack, Google Sheets, custom CRMs. Both
n8n and Zapier are first-class candidates.

## Options considered

1. **n8n (self-host or cloud)** — open-source, self-hostable,
   supports both webhook-triggered and API-triggered workflows,
   node library is sufficient for our fan-outs.
2. **Zapier** — SaaS-only, much larger app directory, simpler
   webhook setup but per-task pricing.
3. **Make (formerly Integromat)** — comparable to Zapier; similar
   trade-offs.

## Decision

**Default to n8n** as the preferred automation adapter (priority
80), with Zapier available as a fallback at priority 70. The
[[Capability Routing|router]] lets operators use whichever they
have configured.

## Rationale

- **Self-hostable** — fits operators running ShopAI on-prem
- **No per-task pricing** — unlimited fan-out for free-tier users
- **Dual trigger mode** — webhook *and* API, we use whichever env
  var the operator sets (`WEBHOOK_URL` / `WEBHOOK_PATH` /
  `WORKFLOW_ID`)

## Consequences

- n8n is listed first in docs, but the hook is vendor-agnostic
- Operators on Zapier just set `ZAPIER_WEBHOOK_URL` and the router
  picks it up
- Future automation vendors (Make, Pipedream) drop in as ~100-line
  adapters with no hook change

## Related

- [[Adapters - Automation]]
- [[Adapter Hooks]]
