---
title: "Adapters - CRM"
tags: [knowledge, adapters, crm]
created: "2026-04-13"
related:
  - "[[_Adapters Catalog]]"
  - "[[_Capabilities MOC]]"
  - "[[Adapter Hooks]]"
  - "[[Use HubSpot for CRM]]"
---

# Adapters - CRM

## Summary

CRM adapters keep a vendor's contact database in sync with new
customers ShopAI sees in the Shopify data phase. The
[[Adapter Hooks|CRM hook]] deduplicates by lower-cased email and
upserts one contact per new address per cycle.

## Adapters

| Adapter | Priority | Auth | Notes |
|---------|----------|------|-------|
| **HubSpot** | 80 | Bearer (`HUBSPOT_API_KEY`) | Idempotent PATCH via `idProperty=email` |

## Capabilities

- `CRM_UPSERT_CONTACT` — create-or-update by email
- `CRM_ADD_NOTE` — attach a note to a contact
- `CRM_CREATE_DEAL` — create a deal tied to a contact
- `CRM_FIND_CONTACT` — look up by email

## Configuration

```env
HUBSPOT_API_KEY=pat-na1-…
```

Optional: `HUBSPOT_PIPELINE_ID` + `HUBSPOT_STAGE_ID` for deal
creation.

## Upsert contract

```python
router.execute(Capability.CRM_UPSERT_CONTACT, {
    "email": "a@example.com",
    "first_name": "Anne",
    "last_name": "A",
    "phone": "+1-555-…",     # optional
    "company": "…",          # optional
})
```

HubSpot's `PATCH /crm/v3/objects/contacts?idProperty=email` makes
the call idempotent — re-running the same customer the next cycle
is a no-op.

## Related

- [[Use HubSpot for CRM]] — ADR
- [[Adapter Hooks]] — primary caller
- [[_Capabilities MOC]]
