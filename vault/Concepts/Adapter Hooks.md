---
title: "Adapter Hooks"
tags: [concept, hooks, adapters, side-effects]
created: "2026-04-13"
related:
  - "[[Controller Loop]]"
  - "[[Capability Routing]]"
  - "[[Adapters - Analytics]]"
  - "[[Adapters - CRM]]"
  - "[[Adapters - Helpdesk]]"
  - "[[Adapters - Automation]]"
  - "[[Best-Effort Adapter Hooks]]"
---

# Adapter Hooks

## Summary

Adapter hooks are the bridge from "cycle finished" to "outside
world notified." They live in `core/autonomous/adapter_hooks.py`
and run once per cycle, right after the vault writers. Each hook
routes through the [[Capability Routing|smart router]] so a single
hook can pick between PostHog / Mixpanel, HubSpot / …, Zendesk /
Crisp / Intercom, Zapier / n8n without any code change.

## The four hooks

### `emit_analytics_events`

- Fires one `shopai_cycle_complete` event per cycle
- Fires one `order_placed` event per new order
- Routed via `ANALYTICS_TRACK_EVENT` → [[Adapters - Analytics]]
- Capped by `SHOPAI_ANALYTICS_ORDER_CAP` (default 25)

### `sync_crm_contacts`

- Upserts unique-email customers into the configured CRM
- Routed via `CRM_UPSERT_CONTACT` → [[Adapters - CRM]]
- Capped by `SHOPAI_CRM_SYNC_CAP` (default 20)
- Deduped by lower-cased email within a cycle

### `create_helpdesk_ticket_for_errors`

- Opens a ticket when `len(phase_errors) >= SHOPAI_HELPDESK_ERROR_THRESHOLD`
  (default 3)
- Routed via `HELPDESK_CREATE_TICKET` → [[Adapters - Helpdesk]]
- Priority `"high"`, tags `["shopai", "autonomous", "degraded-cycle"]`

### `trigger_automation_webhook`

- POSTs the cycle summary to an automation platform
- Routed via `AUTOMATION_TRIGGER` → [[Adapters - Automation]]
- Configurable via `SHOPAI_CYCLE_WEBHOOK_URL` / `_PATH` / `_WORKFLOW_ID`

## Guarantees

- **Best-effort** — a hook failure never breaks the cycle
- **Per-hook isolation** — one hook crashing doesn't stop the others
- **Opt-in by credentials** — no adapter configured → silent no-op
- **Kill-switch** — `SHOPAI_ADAPTER_HOOKS=off` disables all four at once

## Related

- [[Controller Loop]] — caller
- [[Capability Routing]] — dispatch
- [[Best-Effort Adapter Hooks]] — the ADR
- [[Adapters - Analytics]] · [[Adapters - CRM]] ·
  [[Adapters - Helpdesk]] · [[Adapters - Automation]]
- [[Adapter Hooks Shipped]] — the shipping win
