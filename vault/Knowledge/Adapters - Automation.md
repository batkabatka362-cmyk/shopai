---
title: "Adapters - Automation"
tags: [knowledge, adapters, automation, webhook]
created: "2026-04-13"
related:
  - "[[_Adapters Catalog]]"
  - "[[_Capabilities MOC]]"
  - "[[Adapter Hooks]]"
  - "[[Use n8n over Zapier]]"
---

# Adapters - Automation

## Summary

Automation adapters fan ShopAI's cycle summaries out to operator-
owned workflows — Slack posts, Google Sheets rows, custom CRM
flows, whatever. The [[Adapter Hooks|automation hook]] fires once
per cycle if any of the `SHOPAI_CYCLE_WEBHOOK_*` env vars is set.

## Adapters

| Adapter | Priority | Auth | Notes |
|---------|----------|------|-------|
| **n8n** | 80 | `X-N8N-API-KEY` (API mode) or none (webhook mode) | Self-hostable |
| **Zapier** | 70 | Webhook URL | SaaS |

## Capabilities

- `AUTOMATION_TRIGGER` — fire a webhook or workflow
- `AUTOMATION_RUN_WORKFLOW` — (n8n only) run by workflow id

## Configuration

```env
# n8n webhook mode (preferred for dev)
SHOPAI_CYCLE_WEBHOOK_URL=https://n8n.example.com/webhook/abcd

# OR path-only, paired with N8N base url
N8N_BASE_URL=https://n8n.example.com
SHOPAI_CYCLE_WEBHOOK_PATH=/cycle-done

# OR API mode (trigger a workflow by id)
N8N_API_KEY=…
SHOPAI_CYCLE_WORKFLOW_ID=42

# Zapier
ZAPIER_WEBHOOK_URL=https://hooks.zapier.com/hooks/catch/…
```

## Payload shape

```json
{
  "store_id": "shop-A",
  "cycle_id": "cycle_1_100",
  "timestamp": 1712345678.9,
  "duration_s": 1.5,
  "phase_error_count": 0,
  "insights": 4,
  "actions_proposed": 2,
  "status": "complete"
}
```

## Related

- [[Use n8n over Zapier]] — ADR
- [[Adapter Hooks]] — primary caller
- [[_Capabilities MOC]]
