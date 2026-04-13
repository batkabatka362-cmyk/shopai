---
title: "Adapters - Email"
tags: [knowledge, adapters, email, messaging]
created: "2026-04-13"
related:
  - "[[_Adapters Catalog]]"
  - "[[_Capabilities MOC]]"
---

# Adapters - Email

## Summary

Six email adapters cover transactional, marketing, and broadcast
use cases. The [[Capability Routing|router]] picks by priority and
observed deliverability (via `ActionWeightStore`).

## Adapters

| Adapter | Priority | Auth | Specialty |
|---------|----------|------|-----------|
| **Postmark** | 90 | Server token | Transactional, best deliverability |
| **SendGrid** | 85 | Bearer | Transactional + marketing |
| **Resend** | 80 | Bearer | Developer-first, modern API |
| **Brevo** | 75 | `api-key` header | Batteries-included marketing |
| **Klaviyo** | 70 | Bearer | Behavioural / flow-driven |
| **Omnisend** | 60 | Bearer | Shopify-native marketing |

## Capabilities

- `EMAIL_SEND` — one-shot send
- `EMAIL_SEND_TEMPLATE` — vendor-hosted template + merge vars
- `EMAIL_SEND_BATCH` — many recipients in one call

## Routing heuristics

- Transactional (order confirmations, password resets) → **Postmark**
- Marketing flows / abandoned cart → **Klaviyo** or **Omnisend**
- Generic broadcast → **Brevo** or **SendGrid**

## Related

- [[_Capabilities MOC]]
- [[_Adapters Catalog]]
