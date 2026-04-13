---
title: "Adapters - Helpdesk"
tags: [knowledge, adapters, helpdesk]
created: "2026-04-13"
related:
  - "[[_Adapters Catalog]]"
  - "[[_Capabilities MOC]]"
  - "[[Adapter Hooks]]"
---

# Adapters - Helpdesk

## Summary

Helpdesk adapters open support tickets and push messages. ShopAI's
[[Adapter Hooks|helpdesk hook]] opens a ticket only when a cycle
degrades (errors >= `SHOPAI_HELPDESK_ERROR_THRESHOLD`, default 3)
so routine warnings don't spam the support inbox.

## Adapters

| Adapter | Priority | Auth | Notes |
|---------|----------|------|-------|
| **Intercom** | 90 | Bearer | Conversations API |
| **Zendesk** | 80 | Basic `email/token:api_token` | Full CRM-grade helpdesk |
| **Crisp** | 70 | Basic + `X-Crisp-Tier` header | Three-step create flow |

## Capabilities

- `HELPDESK_CREATE_TICKET` — open a ticket with subject/body/tags
- `HELPDESK_UPDATE_TICKET` — change status or add comment
- `HELPDESK_ADD_COMMENT` — append a comment to an existing ticket
- `HELPDESK_SEND_MESSAGE` — send a user-facing message

## Configuration

```env
# Intercom
INTERCOM_ACCESS_TOKEN=…

# Zendesk
ZENDESK_SUBDOMAIN=…
ZENDESK_EMAIL=…
ZENDESK_API_TOKEN=…

# Crisp
CRISP_IDENTIFIER=…
CRISP_KEY=…
CRISP_WEBSITE_ID=…
```

Any one is enough. The router picks by priority.

## Degradation ticket shape

```json
{
  "subject": "[ShopAI] Cycle cycle_1_100 degraded: 3 phase errors",
  "body": "Store: …\nCycle: …\n\nFailed phases:\n  - data: TimeoutError …",
  "priority": "high",
  "tags": ["shopai", "autonomous", "degraded-cycle"],
  "requester_email": "shopai-alerts@<store_id>"
}
```

## Related

- [[Adapter Hooks]] — primary caller
- [[Example Error Pattern]] — what triggers a ticket
- [[_Capabilities MOC]]
