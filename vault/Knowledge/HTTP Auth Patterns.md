---
title: "HTTP Auth Patterns"
tags: [knowledge, http, auth, integration]
created: "2026-04-13"
related:
  - "[[Adapter Pattern]]"
  - "[[_Adapters Catalog]]"
---

# HTTP Auth Patterns

## Summary

Nearly every ShopAI adapter authenticates to a vendor API using one
of four patterns. Knowing which pattern a vendor uses is half the
work of adding a new adapter.

## The four patterns

### 1. Bearer token

Most modern APIs: OpenAI, Anthropic, Groq, Stripe, HubSpot, PostHog,
Brevo, Resend, Klaviyo.

```python
headers = {"Authorization": f"Bearer {api_key}"}
```

### 2. Basic auth

Older or ops-focused APIs: Zendesk, Twilio.

```python
# Zendesk special case — email/token:apitoken
auth = (f"{email}/token", api_token)
# Twilio — account_sid:auth_token
auth = (account_sid, auth_token)
```

### 3. Custom header

Vendor-specific: Mixpanel, Crisp, n8n.

```python
# Crisp
headers = {
    "Authorization": f"Basic {base64(identifier + ':' + key)}",
    "X-Crisp-Tier": "plugin",
}
# n8n
headers = {"X-N8N-API-KEY": api_key}
```

### 4. HMAC signature

Shopify webhooks, Judge.me callbacks.

```python
sig = hmac.new(secret, body, sha256).hexdigest()
# compare against X-Shopify-Hmac-SHA256 header
```

## Tips

- Never log headers. Log `auth_mode="bearer"` instead.
- 401 vs 403 matters — 401 = bad creds, 403 = scope problem
- Rate limits usually sit in `X-RateLimit-Remaining` or `Retry-After`
- Always give the adapter a single `_auth_headers()` helper so tests
  can stub the auth in isolation

## Related

- [[Adapter Pattern]]
- [[_Adapters Catalog]]
