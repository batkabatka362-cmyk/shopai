---
title: "Use HubSpot for CRM"
tags: [decision, crm, adapter, adr]
created: "2026-04-13"
status: "accepted"
outcome: "successful"
related:
  - "[[Adapters - CRM]]"
  - "[[Adapter Hooks]]"
---

# Use HubSpot for CRM

## Context

ShopAI needs to sync new Shopify customers into an operator-owned
CRM so downstream sales/marketing flows see them. Building a CRM
ourselves violates the core principle ("connect, don't rebuild");
we just need a vendor plug.

## Options considered

1. **HubSpot** — mature API, generous free tier, idempotent upsert
   via `idProperty=email`, widely adopted by SMB Shopify operators.
2. **Pipedrive** — cleaner API but narrower adoption among our
   target operators.
3. **Salesforce** — enterprise-grade but huge API surface and
   licence cost; overkill for the target persona.
4. **Custom table in Postgres** — rejected. Not a CRM, no workflow
   layer; operators would need to build everything on top.

## Decision

**HubSpot**, with the [[Adapter Pattern]] letting us slot in
Pipedrive / Salesforce later without touching the [[Adapter Hooks|hook]].

## Consequences

- The CRM hook activates the moment `HUBSPOT_API_KEY` is set — no
  config flag required
- Idempotent upsert means re-running the same customer is safe
- If an operator uses a different CRM, they add one adapter file
  (~150 lines) and the hook picks it up by priority

## Related

- [[Adapters - CRM]]
- [[Adapter Hooks]]
- [[Capability Routing]]
