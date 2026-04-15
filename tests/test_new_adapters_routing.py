"""Smoke test — new adapters routable end-to-end via SmartRouter.

This test asserts the registration → route → execute → metrics
chain works for the adapters added in Wave 2 (Qdrant, Apify)
without any test needing to know the adapter's internals. It's
the autonomous-loop entry test: if this passes, the brain can
ask for VECTOR_STORE or SCRAPE_PAGE and the router will pick
the new adapter + record the outcome.

Scope:

  * bootstrap + route:  after register_all, router.route picks
    the new adapter when configured
  * execute + metrics:  router.execute runs it, MetricsCollector
    observes the call
  * fallback chain:     scrape_page with Apify configured but
    Firecrawl not configured picks Apify; both configured picks
    Firecrawl (primary), router.candidates surfaces Apify second

Real HTTP is forbidden — the adapters' transport methods are
patched.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from core.adapters import (
    Capability,
    RouteContext,
    get_config,
    get_metrics,
    get_registry,
    get_router,
    reset_config,
    reset_metrics,
    reset_registry,
    reset_router,
)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for var in (
        "QDRANT_URL",
        "QDRANT_API_KEY",
        "QDRANT_COLLECTION",
        "PINECONE_API_KEY",
        "WEAVIATE_URL",
        "APIFY_API_TOKEN",
        "FIRECRAWL_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()
    yield
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()


# ══════════════════════════════════════════════════════════════
# Qdrant routing smoke test
# ══════════════════════════════════════════════════════════════


class TestQdrantRoutableEndToEnd:
    def test_bootstrap_makes_qdrant_discoverable(self, monkeypatch):
        from core.adapters.vector.bootstrap import register_all
        monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")
        get_config().reload()

        status = register_all()

        assert status.get("qdrant") is True
        assert "qdrant" in get_registry().names()

    def test_router_picks_qdrant_when_only_qdrant_configured(
        self, monkeypatch,
    ):
        from core.adapters.vector.bootstrap import register_all
        monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")
        get_config().reload()
        register_all()

        adapter = get_router().route(Capability.VECTOR_STORE)
        # With only qdrant configured (pinecone needs API key,
        # weaviate needs library), the router MUST pick qdrant.
        assert adapter.name == "qdrant"

    def test_router_execute_records_qdrant_outcome(self, monkeypatch):
        """End-to-end: register, route, execute, metrics captured."""
        from core.adapters.vector.bootstrap import register_all
        from core.adapters.vector.qdrant import QdrantAdapter

        monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")
        get_config().reload()
        register_all()

        # Patch at the class level so whichever instance the
        # registry holds receives the patched method.
        with patch.object(
            QdrantAdapter, "_http_request",
            return_value={"status": "ok"},
        ):
            result = get_router().execute(
                Capability.VECTOR_STORE,
                {
                    "vectors": [
                        {
                            "id": "smoke-1",
                            "vector": [0.1, 0.2, 0.3],
                            "metadata": {"source": "smoke-test"},
                        },
                    ],
                },
            )

        assert result.ok, f"router.execute failed: {result.error}"
        assert result.data["upserted_count"] == 1

        # Metrics collector must have observed the call so
        # ActionWeightStore can learn the success.
        snapshot = get_metrics().snapshot()
        assert any(
            # The snapshot includes per-adapter entries; we're
            # asserting qdrant made it into one of them.
            "qdrant" in str(entry).lower()
            for entry in snapshot
        ), f"qdrant not in metrics snapshot: {snapshot!r}"


# ══════════════════════════════════════════════════════════════
# Apify routing smoke test
# ══════════════════════════════════════════════════════════════


class TestApifyRoutableEndToEnd:
    def test_bootstrap_makes_apify_discoverable(self, monkeypatch):
        from core.adapters.scraper.bootstrap import register_all
        monkeypatch.setenv("APIFY_API_TOKEN", "apify-test")
        get_config().reload()

        status = register_all()

        assert status.get("apify") is True
        assert "apify" in get_registry().names()

    def test_router_picks_apify_when_only_apify_configured(
        self, monkeypatch,
    ):
        """With Firecrawl unconfigured, the router falls
        through to Apify for SCRAPE_PAGE."""
        from core.adapters.scraper.bootstrap import register_all
        monkeypatch.setenv("APIFY_API_TOKEN", "apify-test")
        get_config().reload()
        register_all()

        adapter = get_router().route(Capability.SCRAPE_PAGE)
        assert adapter.name == "apify"

    def test_router_prefers_firecrawl_when_both_configured(
        self, monkeypatch,
    ):
        """Both configured: Firecrawl wins on priority (80 > 70)
        but Apify shows up in the fallback chain."""
        from core.adapters.scraper.bootstrap import register_all
        monkeypatch.setenv("APIFY_API_TOKEN", "apify-test")
        monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-test")
        get_config().reload()
        register_all()

        router = get_router()
        primary = router.route(Capability.SCRAPE_PAGE)
        assert primary.name == "firecrawl"

        names = [a.name for a in router.candidates(Capability.SCRAPE_PAGE)]
        assert names[0] == "firecrawl"
        assert "apify" in names, f"Apify missing from fallback chain: {names}"

    def test_router_execute_with_apify(self, monkeypatch):
        """End-to-end scrape → normalised result."""
        from core.adapters.scraper.bootstrap import register_all
        from core.adapters.scraper.apify import ApifyAdapter

        monkeypatch.setenv("APIFY_API_TOKEN", "apify-test")
        get_config().reload()
        register_all()

        canned = [{
            "url": "https://example.com/p",
            "loadedUrl": "https://example.com/p",
            "title": "Smoke Test Page",
            "text": "hello",
            "markdown": "# Smoke\n",
            "html": "",
            "metadata": {},
            "crawl": {"httpStatusCode": 200},
        }]
        with patch.object(
            ApifyAdapter, "_http_post", return_value=canned,
        ):
            result = get_router().execute(
                Capability.SCRAPE_PAGE,
                {"url": "https://example.com/p"},
            )

        assert result.ok, f"router.execute failed: {result.error}"
        assert result.data["title"] == "Smoke Test Page"
        assert result.data["status"] == 200


# ══════════════════════════════════════════════════════════════
# Unconfigured case — router surfaces NoAdapterAvailable loudly
# ══════════════════════════════════════════════════════════════


class TestUnconfiguredCapabilityFailsLoudly:
    def test_scrape_page_without_any_scraper_configured(self):
        """Neither Firecrawl nor Apify configured → router must
        refuse instead of silently returning empty data."""
        from core.adapters.scraper.bootstrap import register_all
        register_all()

        result = get_router().execute(
            Capability.SCRAPE_PAGE,
            {"url": "https://example.com/"},
        )
        # No adapter satisfies → router returns failure result
        # so the autonomous loop records an explicit negative
        # outcome in ActionWeightStore (rather than a phantom
        # success that would poison learning).
        assert not result.ok
