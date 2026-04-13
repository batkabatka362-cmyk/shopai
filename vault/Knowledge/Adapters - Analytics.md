---
title: "Adapters - Analytics"
tags: [knowledge, adapters, analytics]
created: "2026-04-13"
related:
  - "[[_Adapters Catalog]]"
  - "[[_Capabilities MOC]]"
  - "[[Adapter Hooks]]"
---

# Adapters - Analytics

## Summary

Analytics adapters emit product-event telemetry. ShopAI fires
`shopai_cycle_complete` and `order_placed` events on every cycle
(see [[Adapter Hooks|the analytics hook]]). The [[Capability Routing|router]]
picks whichever analytics vendor is configured.

## Adapters

| Adapter | Priority | Auth | Notes |
|---------|----------|------|-------|
| **PostHog** | 80 | Bearer | OSS-friendly, event capture + feature flags |
| **Mixpanel** | 70 | Token + secret (basic) | Rich funnel tooling |

## Capabilities

- `ANALYTICS_TRACK_EVENT` — fire a named event
- `ANALYTICS_IDENTIFY` — associate traits with a distinct_id

## Configuration

```env
POSTHOG_API_KEY=phc_…
POSTHOG_HOST=https://app.posthog.com   # or EU / self-hosted

MIXPANEL_TOKEN=…
MIXPANEL_API_SECRET=…
```

Set either one (or both) and the analytics hook activates. With
both set, PostHog wins on priority but Mixpanel is the fallback.

## Event schema (from ShopAI)

```json
{
  "event": "shopai_cycle_complete",
  "distinct_id": "store:<store_id>",
  "properties": {
    "store_id": "...", "cycle_id": "...",
    "duration_s": 1.5, "phase_error_count": 0,
    "insights": 4, "actions_proposed": 2
  }
}
```

Order events use `distinct_id = customer_id` and `properties`
include `order_id`, `total_price`, `currency`, `line_items_count`.

## Related

- [[Adapter Hooks]] — primary caller
- [[_Capabilities MOC]]
- [[_Adapters Catalog]]
