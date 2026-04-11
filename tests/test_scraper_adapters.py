"""Regression tests for the scraper adapter family.

Wave 1 extension — Firecrawl only.

Real HTTP calls are forbidden — every test patches the
adapter's ``_http_post`` helper so the suite stays hermetic.

Coverage matrix:

  * Capability enum exposes SCRAPE_PAGE
  * ScraperBaseAdapter validates inputs (url required + http(s)
    scheme, formats type, wait_for range) and rejects unknown
    capabilities
  * FirecrawlAdapter
        - registry metadata (name, category, capabilities,
          priority, cost)
        - is_configured() requires FIRECRAWL_API_KEY
        - _scrape_url points at /v0/scrape
        - _auth_headers use Bearer
        - payload: pageOptions (onlyMainContent, includeTags,
          excludeTags, waitFor), includeHtml when html format
          requested
        - parse unwraps {success, data, metadata} envelope
        - parse flat response tolerated
        - parse success=false raises AdapterError
        - happy path captures markdown + html + title + status
        - HTTP error mapping (auth, rate limit)
  * Bootstrap
        - register_all adds the adapter, idempotent
        - status map reflects is_configured
  * SmartRouter
        - routes SCRAPE_PAGE to firecrawl when configured
        - raises NoAdapterAvailable when unconfigured
        - end-to-end execute() succeeds and the metrics collector
          captures the outcome INCLUDING cost_usd=0.002
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from core.adapters import (
    AdapterAuthError,
    AdapterCategory,
    AdapterRateLimited,
    AdapterValidationError,
    Capability,
    NoAdapterAvailable,
    get_config,
    get_metrics,
    get_registry,
    get_router,
    reset_config,
    reset_metrics,
    reset_registry,
    reset_router,
)


# ── Fixtures ────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    """Clear Firecrawl env + every adapter singleton between tests."""
    for var in (
        "FIRECRAWL_API_KEY",
        "BREVO_API_KEY",
        "RESEND_API_KEY",
        "OPENAI_API_KEY",
        "TWILIO_ACCOUNT_SID",
        "TWILIO_AUTH_TOKEN",
        "TWILIO_FROM_NUMBER",
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


def _configure_firecrawl(monkeypatch) -> None:
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-test-xxxxxxxx")
    get_config().reload()


_VALID_SCRAPE = {
    "url": "https://competitor.example.com/products/1",
    "only_main_content": True,
    "formats": ["markdown"],
}


# ── Capability enum ─────────────────────────────────────────


class TestScraperCapabilities:
    def test_scrape_page_capability_exists(self):
        assert Capability("scrape_page") is Capability.SCRAPE_PAGE


# ── ScraperBaseAdapter validation ───────────────────────────


class TestScraperBaseAdapter:
    def test_url_is_required(self, monkeypatch):
        from core.adapters.scraper.firecrawl import FirecrawlAdapter
        _configure_firecrawl(monkeypatch)
        a = FirecrawlAdapter()
        result = a.execute(Capability.SCRAPE_PAGE, {})
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)
        assert "url" in result.error.reason

    def test_url_must_be_http_scheme(self, monkeypatch):
        from core.adapters.scraper.firecrawl import FirecrawlAdapter
        _configure_firecrawl(monkeypatch)
        a = FirecrawlAdapter()
        result = a.execute(
            Capability.SCRAPE_PAGE,
            {"url": "ftp://files.example.com/file.txt"},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)
        assert "http" in result.error.reason.lower()

    def test_formats_must_be_list(self, monkeypatch):
        from core.adapters.scraper.firecrawl import FirecrawlAdapter
        _configure_firecrawl(monkeypatch)
        a = FirecrawlAdapter()
        result = a.execute(
            Capability.SCRAPE_PAGE,
            {"url": "https://x.example.com", "formats": "markdown"},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_wait_for_range_rejected(self, monkeypatch):
        from core.adapters.scraper.firecrawl import FirecrawlAdapter
        _configure_firecrawl(monkeypatch)
        a = FirecrawlAdapter()
        result = a.execute(
            Capability.SCRAPE_PAGE,
            {"url": "https://x.example.com", "wait_for": 99_999},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_wait_for_non_numeric_rejected(self, monkeypatch):
        from core.adapters.scraper.firecrawl import FirecrawlAdapter
        _configure_firecrawl(monkeypatch)
        a = FirecrawlAdapter()
        result = a.execute(
            Capability.SCRAPE_PAGE,
            {"url": "https://x.example.com", "wait_for": "soon"},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_unknown_capability_returns_validation_error(self, monkeypatch):
        from core.adapters.scraper.firecrawl import FirecrawlAdapter
        _configure_firecrawl(monkeypatch)
        a = FirecrawlAdapter()
        result = a.execute(Capability.SEND_EMAIL_TRANSACTIONAL, {})
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)


# ── FirecrawlAdapter ────────────────────────────────────────


class TestFirecrawlAdapter:
    def test_metadata(self):
        from core.adapters.scraper.firecrawl import FirecrawlAdapter
        a = FirecrawlAdapter()
        assert a.name == "firecrawl"
        assert a.category == AdapterCategory.SCRAPER
        assert Capability.SCRAPE_PAGE in a.capabilities
        assert a.priority == 80
        assert a.cost_per_call == 0.002

    def test_unconfigured_without_key(self):
        from core.adapters.scraper.firecrawl import FirecrawlAdapter
        assert not FirecrawlAdapter().is_configured()

    def test_configured_with_api_key(self, monkeypatch):
        from core.adapters.scraper.firecrawl import FirecrawlAdapter
        _configure_firecrawl(monkeypatch)
        assert FirecrawlAdapter().is_configured()

    def test_scrape_url(self):
        from core.adapters.scraper.firecrawl import FirecrawlAdapter
        a = FirecrawlAdapter()
        assert a._scrape_url() == "https://api.firecrawl.dev/v0/scrape"

    def test_auth_headers_use_bearer(self, monkeypatch):
        from core.adapters.scraper.firecrawl import FirecrawlAdapter
        _configure_firecrawl(monkeypatch)
        a = FirecrawlAdapter()
        headers = a._auth_headers()
        assert headers["Authorization"] == "Bearer fc-test-xxxxxxxx"
        assert headers["Content-Type"] == "application/json"

    def test_payload_basic(self, monkeypatch):
        from core.adapters.scraper.firecrawl import FirecrawlAdapter
        _configure_firecrawl(monkeypatch)
        a = FirecrawlAdapter()
        body = a._build_scrape_payload({"url": "https://x.example.com"})
        assert body == {"url": "https://x.example.com"}

    def test_payload_with_page_options(self, monkeypatch):
        from core.adapters.scraper.firecrawl import FirecrawlAdapter
        _configure_firecrawl(monkeypatch)
        a = FirecrawlAdapter()
        body = a._build_scrape_payload({
            "url": "https://x.example.com",
            "only_main_content": True,
            "include_tags": ["article", "main"],
            "exclude_tags": ["nav"],
            "wait_for": 1_500,
        })
        assert body["url"] == "https://x.example.com"
        assert body["pageOptions"]["onlyMainContent"] is True
        assert body["pageOptions"]["includeTags"] == ["article", "main"]
        assert body["pageOptions"]["excludeTags"] == ["nav"]
        assert body["pageOptions"]["waitFor"] == 1_500

    def test_payload_html_format_sets_include_html(self, monkeypatch):
        from core.adapters.scraper.firecrawl import FirecrawlAdapter
        _configure_firecrawl(monkeypatch)
        a = FirecrawlAdapter()
        body = a._build_scrape_payload({
            "url": "https://x.example.com",
            "formats": ["markdown", "html"],
        })
        assert body["pageOptions"]["includeHtml"] is True


# ── Scrape happy path ───────────────────────────────────────


class TestFirecrawlScrape:
    def test_scrape_happy_path(self, monkeypatch):
        from core.adapters.scraper.firecrawl import FirecrawlAdapter
        _configure_firecrawl(monkeypatch)
        a = FirecrawlAdapter()

        captured = {}

        def fake_post(url, body, headers):
            captured["url"] = url
            captured["body"] = body
            captured["headers"] = headers
            return {
                "success": True,
                "data": {
                    "markdown": "# Product name\n\nPrice: $49.99",
                    "html": "<article>Product</article>",
                    "metadata": {
                        "title": "Product name — Competitor",
                        "description": "A lovely widget",
                        "sourceURL": "https://competitor.example.com/products/1",
                        "statusCode": 200,
                    },
                },
            }

        with patch.object(a, "_http_post", side_effect=fake_post):
            result = a.execute(
                Capability.SCRAPE_PAGE, dict(_VALID_SCRAPE),
            )

        assert result.ok
        assert result.data["url"] == (
            "https://competitor.example.com/products/1"
        )
        assert result.data["title"] == "Product name — Competitor"
        assert result.data["markdown"] == "# Product name\n\nPrice: $49.99"
        assert result.data["html"] == "<article>Product</article>"
        assert result.data["status"] == 200
        assert result.data["metadata"]["description"] == "A lovely widget"
        assert result.cost_usd == pytest.approx(0.002)

        assert captured["url"].endswith("/v0/scrape")
        assert captured["body"]["url"] == _VALID_SCRAPE["url"]
        assert captured["body"]["pageOptions"]["onlyMainContent"] is True
        assert captured["headers"]["Authorization"] == (
            "Bearer fc-test-xxxxxxxx"
        )

    def test_scrape_flat_response_tolerated(self, monkeypatch):
        """Some Firecrawl responses skip the {data: ...} envelope.
        The parser must still extract the payload."""
        from core.adapters.scraper.firecrawl import FirecrawlAdapter
        _configure_firecrawl(monkeypatch)
        a = FirecrawlAdapter()

        def fake_post(url, body, headers):
            return {
                "markdown": "# Flat",
                "metadata": {"title": "Flat page", "statusCode": 200},
            }

        with patch.object(a, "_http_post", side_effect=fake_post):
            result = a.execute(
                Capability.SCRAPE_PAGE,
                {"url": "https://x.example.com"},
            )

        assert result.ok
        assert result.data["markdown"] == "# Flat"
        assert result.data["title"] == "Flat page"

    def test_scrape_success_false_raises(self, monkeypatch):
        """Firecrawl's ``success: false`` must become a failed
        AdapterResult so the metrics layer records a failure,
        not a phantom success."""
        from core.adapters.scraper.firecrawl import FirecrawlAdapter
        from core.adapters.errors import AdapterError
        _configure_firecrawl(monkeypatch)
        a = FirecrawlAdapter()

        def fake_post(url, body, headers):
            return {
                "success": False,
                "error": "robots.txt disallows scraping",
            }

        with patch.object(a, "_http_post", side_effect=fake_post):
            result = a.execute(
                Capability.SCRAPE_PAGE, dict(_VALID_SCRAPE),
            )
        assert not result.ok
        assert isinstance(result.error, AdapterError)
        assert "robots.txt" in result.error.reason

    def test_scrape_non_dict_response_raises(self, monkeypatch):
        from core.adapters.scraper.firecrawl import FirecrawlAdapter
        from core.adapters.errors import AdapterError
        _configure_firecrawl(monkeypatch)
        a = FirecrawlAdapter()
        with patch.object(a, "_http_post", return_value="not-a-dict"):
            result = a.execute(
                Capability.SCRAPE_PAGE, dict(_VALID_SCRAPE),
            )
        assert not result.ok
        assert isinstance(result.error, AdapterError)

    def test_scrape_auth_error_mapped(self, monkeypatch):
        from core.adapters.scraper.firecrawl import FirecrawlAdapter
        _configure_firecrawl(monkeypatch)
        a = FirecrawlAdapter()
        with patch.object(
            a, "_http_post",
            side_effect=AdapterAuthError(a.name, "bad key"),
        ):
            result = a.execute(
                Capability.SCRAPE_PAGE, dict(_VALID_SCRAPE),
            )
        assert not result.ok
        assert isinstance(result.error, AdapterAuthError)

    def test_scrape_rate_limit_mapped(self, monkeypatch):
        from core.adapters.scraper.firecrawl import FirecrawlAdapter
        _configure_firecrawl(monkeypatch)
        a = FirecrawlAdapter()
        with patch.object(
            a, "_http_post",
            side_effect=AdapterRateLimited(a.name, "throttled"),
        ):
            result = a.execute(
                Capability.SCRAPE_PAGE, dict(_VALID_SCRAPE),
            )
        assert not result.ok
        assert isinstance(result.error, AdapterRateLimited)


# ── Bootstrap ───────────────────────────────────────────────


class TestScraperBootstrap:
    def test_register_all_adds_firecrawl(self):
        from core.adapters.scraper.bootstrap import register_all
        status = register_all()
        assert "firecrawl" in status

    def test_register_all_unconfigured_without_env(self):
        from core.adapters.scraper.bootstrap import register_all
        status = register_all()
        assert status["firecrawl"] is False

    def test_register_all_configured_when_env_set(self, monkeypatch):
        from core.adapters.scraper.bootstrap import register_all
        _configure_firecrawl(monkeypatch)
        status = register_all()
        assert status["firecrawl"] is True

    def test_register_all_idempotent(self):
        from core.adapters.scraper.bootstrap import register_all
        register_all()
        register_all()
        assert len([
            n for n in get_registry().names() if n == "firecrawl"
        ]) == 1


# ── Smart router routing + metrics capture ──────────────────


class TestScraperRouterIntegration:
    def test_router_routes_scrape_page_to_firecrawl(self, monkeypatch):
        from core.adapters.scraper.bootstrap import register_all
        _configure_firecrawl(monkeypatch)
        register_all()
        chosen = get_router().route(Capability.SCRAPE_PAGE)
        assert chosen.name == "firecrawl"

    def test_router_raises_when_firecrawl_unconfigured(self):
        from core.adapters.scraper.bootstrap import register_all
        register_all()
        with pytest.raises(NoAdapterAvailable):
            get_router().route(Capability.SCRAPE_PAGE)

    def test_end_to_end_scrape_records_metrics(self, monkeypatch):
        """Wave 1 success criterion — the router reaches a brand-new
        external system AND MetricsCollector captures the outcome,
        INCLUDING cost_usd=0.002 so scraping spend shows up
        separately in the budget advisor."""
        from core.adapters.scraper.bootstrap import register_all
        from core.adapters.scraper.firecrawl import FirecrawlAdapter

        _configure_firecrawl(monkeypatch)
        register_all()

        adapter = get_registry().get("firecrawl")
        assert isinstance(adapter, FirecrawlAdapter)

        def fake_post(url, body, headers):
            return {
                "success": True,
                "data": {
                    "markdown": "# Scraped",
                    "metadata": {
                        "title": "Test", "statusCode": 200,
                        "sourceURL": "https://x.example.com",
                    },
                },
            }

        with patch.object(adapter, "_http_post", side_effect=fake_post):
            result = get_router().execute(
                Capability.SCRAPE_PAGE,
                {"url": "https://x.example.com"},
            )

        assert result.ok
        assert result.adapter == "firecrawl"
        assert result.capability == "scrape_page"
        assert result.data["markdown"] == "# Scraped"
        assert result.cost_usd == pytest.approx(0.002)

        stats = get_metrics().stats_for("firecrawl")
        assert stats is not None
        assert stats["calls_total"] == 1
        assert stats["calls_success"] == 1
        assert stats["calls_failure"] == 0
        assert stats["success_rate"] == 1.0

    def test_router_records_failure_metric(self, monkeypatch):
        from core.adapters.scraper.bootstrap import register_all
        from core.adapters.scraper.firecrawl import FirecrawlAdapter

        _configure_firecrawl(monkeypatch)
        register_all()
        adapter = get_registry().get("firecrawl")
        assert isinstance(adapter, FirecrawlAdapter)

        with patch.object(
            adapter, "_http_post",
            side_effect=AdapterAuthError(adapter.name, "bad key"),
        ):
            result = get_router().execute(
                Capability.SCRAPE_PAGE,
                {"url": "https://x.example.com"},
            )

        assert not result.ok
        stats = get_metrics().stats_for("firecrawl")
        assert stats is not None
        assert stats["calls_total"] == 1
        assert stats["calls_failure"] == 1
        assert stats["calls_success"] == 0
