---
title: "Example Error Pattern"
tags: [error, postmortem, example]
created: "2026-04-13"
severity: "medium"
status: "resolved"
related:
  - "[[Adapter Pattern]]"
  - "[[ShopAI Architecture]]"
---

# Registry .all() Method Missing

## What Happened

The dashboard API handler called `reg.all()` to iterate adapters, but `AdapterRegistry` has no `all()` method. All 6 dashboard endpoints returned empty data.

## Root Cause

Assumed the registry had an `all()` method from standard dict-like interfaces. The actual API uses `names()` + `get(name)` pattern for iteration.

## Impact

- Affected systems: Dashboard (all 5 tabs showed empty)
- Duration: Caught during development
- User impact: None (pre-release)

## Fix Applied

Created `_iter_adapters()` static method:
```python
for name in reg.names():
    adapter = reg.get(name)
    if adapter is not None:
        yield adapter
```
Replaced all 6 occurrences of `reg.all()`.

## Lessons Learned

- Always check the actual API before assuming standard methods exist
- The [[Adapter Pattern]] registry uses `names()` + `get()`, not `all()`
- Write a helper once, use everywhere

## Prevention

- Read source code before using internal APIs
- Integration tests for dashboard endpoints
