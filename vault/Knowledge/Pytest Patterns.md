---
title: "Pytest Patterns"
tags: [knowledge, pytest, testing]
created: "2026-04-13"
related:
  - "[[Adapter Pattern]]"
  - "[[ShopAI Architecture]]"
---

# Pytest Patterns

## Summary

ShopAI's test suite leans on three pytest fixtures heavily:
`monkeypatch`, `tmp_path`, and `MagicMock`. Together they let us
test the controller, the smart router, and every adapter in full
isolation — no real HTTP, no real disk, no real environment.

## The three patterns

### 1. Environment isolation with `monkeypatch`

```python
def test_something(monkeypatch):
    monkeypatch.setenv("SHOPAI_ADAPTER_HOOKS", "off")
    # test runs with env flipped; pytest restores on teardown
```

- Always use `monkeypatch.setenv` / `delenv` — never `os.environ[...]`
- Always call `reset_config()` after modifying env vars if any
  adapter reads config

### 2. Scratch filesystem with `tmp_path`

```python
def test_vault(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(vault))
    # write notes, assert file layout
```

`tmp_path` is unique per test and auto-cleaned. No more `/tmp/test-…`
collisions.

### 3. Mock router with `MagicMock`

```python
from unittest.mock import MagicMock
from core.adapters.base import AdapterResult

def _fake_router(result=None):
    r = MagicMock()
    r.execute = MagicMock(return_value=result or AdapterResult(
        ok=True, adapter="stub", capability="x", data={},
    ))
    return r
```

This is how [[Adapter Hooks]] tests stub the smart router instead
of registering real adapters.

## Conventions in this repo

- One test class per concern: `TestAnalyticsEvents`, `TestCrmSync`
- Fixtures at class or module level, never global
- Assertion style: `assert x == y` (no `unittest.TestCase`)
- Tests for the same module live in `tests/test_<module>.py`

## Related

- [[Adapter Pattern]] — what the tests exercise
- [[Adapter Hooks]] — exemplar test file
- [[ShopAI Architecture]]
