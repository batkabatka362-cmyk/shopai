---
title: "Adapter Pattern"
tags: [concept, architecture, adapters]
created: "2026-04-13"
related:
  - "[[ShopAI Architecture]]"
---

# Adapter Pattern

## Summary

Every external service in ShopAI is wrapped in a thin adapter that follows the `BaseAdapter` interface. The SmartRouter automatically discovers and routes to adapters based on capabilities, priority, and availability.

## How It Works

```
Brain decides action -> SmartRouter picks adapter -> Adapter calls external API -> Result flows back
```

### BaseAdapter Contract

Every adapter must implement:
- `name` - Unique identifier (e.g., "klaviyo", "stripe")
- `category` - AdapterCategory enum (e.g., EMAIL, ADS, VOICE)
- `capabilities` - Set of Capability enums (what it can do)
- `is_configured()` - Whether credentials are present
- `_execute(capability, params)` - The actual work
- `priority` - Router preference (0-100, higher = preferred)

### SmartRouter Selection

1. Find all adapters with the requested capability
2. Filter to only `is_configured() == True`
3. Sort by priority (descending)
4. Pick the top one; fallback to next on failure
5. ActionWeightStore adjusts weights by observed outcomes

### Creating a New Adapter

Each adapter group follows the same structure:
```
core/adapters/<category>/
    __init__.py      - Package exports
    _base.py         - CategoryBaseAdapter with shared logic
    vendor.py        - Concrete adapter (~100-200 lines)
    bootstrap.py     - register_all() function
```

## Key Design Decisions

- **Extensible groups** - Each category has a base adapter; adding a new vendor is ~100 lines
- **No vendor lock-in** - Router can switch between providers automatically
- **Graceful degradation** - Unconfigured adapters register but are skipped
- **Cost-aware routing** - `cost_per_call` and `estimate_cost()` for budget management

## Related

- [[ShopAI Architecture]] - System overview
- [[Shopify API Basics]] - Primary integration target
