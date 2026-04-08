"""Test-suite-wide fixtures.

The autouse fixtures here block real network egress from the
adapter layer. Without them, integration tests that run a full
autonomous cycle would call ``DDGSAdapter._http_get`` for real
(DDGS is the only search adapter "configured" without an API
key, so the SmartRouter picks it for every search), and the
20-minute slowdown observed pre-fix was the result.

The block is intentionally narrow:

  * ``DDGSAdapter._http_get`` returns an empty HTML body so
    parsing yields zero hits — the engine flow's "no results"
    branch fires cleanly.
  * Other adapters (Brave, Serper, every Shopify adapter,
    every LLM adapter) are NOT patched here because they all
    require API keys / tokens that the test environment never
    sets, so ``is_configured()`` already keeps them off the
    network.

Tests that explicitly want to verify DDGS HTML parsing patch
``_http_get`` themselves with their own canned HTML — those
local patches still work because pytest applies fixture
patches per-test, not globally.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _block_ddgs_network(monkeypatch):
    """Patch ``DDGSAdapter._http_get`` so it never makes a real
    HTTP call during the test suite.

    Returns an empty HTML body so the parser yields zero hits;
    the engine's "no results" branch handles the rest.

    Tests that need to assert DDGS parser behaviour patch
    ``_http_get`` again inside their own ``with patch.object(...)``
    block — those local patches override this autouse fixture
    for the duration of the test.
    """
    try:
        from core.adapters.search.ddgs import DDGSAdapter
    except Exception:
        return
    monkeypatch.setattr(
        DDGSAdapter,
        "_http_get",
        lambda self, url, headers=None: "",
    )
