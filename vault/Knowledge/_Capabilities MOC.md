---
title: "_Capabilities MOC"
tags: [moc, capabilities, index]
created: "2026-04-13"
aliases: ["Capabilities Map"]
related:
  - "[[00 Home]]"
  - "[[Adapter Pattern]]"
  - "[[_Adapters Catalog]]"
---

# _Capabilities MOC

> The `Capability` enum is the contract between the brain and the
> adapter layer. The brain requests a capability; the
> [[Capability Routing|smart router]] picks the best-configured
> adapter that offers it. This index lists every capability,
> grouped by concern, with the adapters that satisfy it.

## LLM

- `LLM_COMPLETE`, `LLM_CHAT`, `LLM_EMBED` → [[Adapters - LLM]]

## Communication

- `EMAIL_SEND`, `EMAIL_SEND_TEMPLATE`, `EMAIL_SEND_BATCH` → [[Adapters - Email]]
- `SMS_SEND`, `SMS_SEND_BATCH` → Twilio, MessageBird
- `VOICE_SYNTHESIZE` → ElevenLabs

## Commerce

- `PAYMENT_CHARGE`, `PAYMENT_REFUND` → Stripe, PayPal
- `ADS_CREATE_CAMPAIGN`, `ADS_REPORT` → Google Ads, Meta Ads
- `SUBSCRIPTION_CREATE`, `SUBSCRIPTION_CANCEL` → ReCharge
- `REVIEW_FETCH`, `REVIEW_REQUEST` → Judge.me

## Search & intelligence

- `SEARCH_WEB`, `SEARCH_SEMANTIC`, `TRAFFIC_ESTIMATE` → [[Adapters - Search]]

## Data

- `VECTOR_UPSERT`, `VECTOR_QUERY` → Weaviate, Pinecone
- `SCRAPE_URL`, `BROWSER_NAVIGATE` → Firecrawl, Playwright

## Analytics & CRM

- `ANALYTICS_TRACK_EVENT`, `ANALYTICS_IDENTIFY` → [[Adapters - Analytics]]
- `CRM_UPSERT_CONTACT`, `CRM_ADD_NOTE`, `CRM_CREATE_DEAL`, `CRM_FIND_CONTACT`
  → [[Adapters - CRM]]

## Support & workflow

- `HELPDESK_CREATE_TICKET`, `HELPDESK_UPDATE_TICKET`,
  `HELPDESK_ADD_COMMENT`, `HELPDESK_SEND_MESSAGE`
  → [[Adapters - Helpdesk]]
- `AUTOMATION_TRIGGER`, `AUTOMATION_RUN_WORKFLOW`
  → [[Adapters - Automation]]

## Image

- `IMAGE_GENERATE`, `IMAGE_EDIT`, `IMAGE_REMOVE_BACKGROUND`
  → DALL-E 3, Stability AI, Remove.bg

## Vault / memory

- `VAULT_READ_NOTES`, `VAULT_SEARCH_NOTES`, `VAULT_WRITE_NOTE`
  → [[Obsidian Integration]]

## Related

- [[Adapter Pattern]]
- [[Capability Routing]]
- [[_Adapters Catalog]]
- [[00 Home]]
