"""Tests for the Apify scraper adapter.

Real HTTP calls are forbidden — every test patches
``_http_post`` to return canned responses.

Coverage:
  * Metadata (name, category, capabilities, priority, cost)
  * is_configured() via APIFY_API_TOKEN
  * _scrape_url builds the run-sync endpoint with ~-separator
  * Custom actor via params["actor"]
  * Bearer header auth
  * Payload translation (startUrls, maxCrawlPages=1, crawlerType,
    exclude_tags → removeElementsCssSelector, wait_for → secs,
    saveHtml gated on formats=["html"])
  * custom_input pass-through
  * Response parsing (array shape, preferred loadedUrl, status
    from crawl.httpStatusCode)
  * Empty array → AdapterError
  * Non-array → AdapterError
  * Bootstrap idempotency
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from core.adapters import (
    AdapterCategory,
    AdapterValidationError,
    Capability,
    get_config,
    get_registry,
    reset_config,
    reset_metrics,
    reset_registry,
    reset_router,
)
from core.adapters.errors import AdapterError


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for var in (
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


def _configure(monkeypatch, *, token="apify-secret"):
    monkeypatch.setenv("APIFY_API_TOKEN", token)
    get_config().reload()


_VALID_SCRAPE = {
    "url": "https://competitor.example.com/products/42",
    "only_main_content": True,
    "formats": ["markdown"],
}


# Canned response mimicking Apify's run-sync-get-dataset-items shape.
_CANNED_APIFY_ITEM = {
    "url": "https://competitor.example.com/products/42",
    "loadedUrl": "https://competitor.example.com/products/42?utm=apify",
    "title": "Widget 42 — Competitor Store",
    "text": "Widget 42 plain text body",
    "markdown": "# Widget 42\n\nCompetitor description",
    "html": "<article>Widget 42</article>",
    "metadata": {
        "description": "The best widget",
        "keywords": "widget, 42",
    },
    "crawl": {
        "httpStatusCode": 200,
        "loadedTime": "2026-01-01T00:00:00Z",
    },
}


# ── Metadata ──────────────────────────────────────────────────


class TestApifyMetadata:
    def test_metadata(self):
        from core.adapters.scraper.apify import ApifyAdapter
        a = ApifyAdapter()
        assert a.name == "apify"
        assert a.category == AdapterCategory.SCRAPER
        assert Capability.SCRAPE_PAGE in a.capabilities
        # Apify priority stays below Firecrawl so the router
        # prefers Firecrawl by default.
        assert a.priority == 70
        assert a.cost_per_call > 0

    def test_unconfigured_without_token(self):
        from core.adapters.scraper.apify import ApifyAdapter
        assert not ApifyAdapter().is_configured()

    def test_configured_with_token(self, monkeypatch):
        from core.adapters.scraper.apify import ApifyAdapter
        _configure(monkeypatch)
        assert ApifyAdapter().is_configured()


# ── URL + auth ───────────────────────────────────────────────


class TestApifyUrl:
    def test_default_actor_url_uses_tilde_separator(self, monkeypatch):
        from core.adapters.scraper.apify import ApifyAdapter
        _configure(monkeypatch)
        a = ApifyAdapter()
        url = a._scrape_url({})
        # The default actor "apify/website-content-crawler" must
        # appear in the URL with ~-separator so it doesn't
        # collide with the REST path hierarchy.
        assert "apify~website-content-crawler" in url
        assert url.endswith("/run-sync-get-dataset-items")

    def test_custom_actor(self, monkeypatch):
        from core.adapters.scraper.apify import ApifyAdapter
        _configure(monkeypatch)
        a = ApifyAdapter()
        url = a._scrape_url({"actor": "myuser/my-actor"})
        assert "myuser~my-actor" in url

    def test_bearer_auth_header(self, monkeypatch):
        from core.adapters.scraper.apify import ApifyAdapter
        _configure(monkeypatch, token="my-apify-secret")
        a = ApifyAdapter()
        headers = a._auth_headers()
        assert headers["Authorization"] == "Bearer my-apify-secret"


# ── Payload translation ──────────────────────────────────────


class TestApifyPayload:
    def test_default_payload_single_page(self, monkeypatch):
        from core.adapters.scraper.apify import ApifyAdapter
        _configure(monkeypatch)
        a = ApifyAdapter()
        body = a._build_scrape_payload(_VALID_SCRAPE)
        assert body["startUrls"] == [
            {"url": "https://competitor.example.com/products/42"},
        ]
        assert body["maxCrawlDepth"] == 0
        assert body["maxCrawlPages"] == 1
        assert body["crawlerType"] == "playwright:chrome"
        assert body["saveMarkdown"] is True
        # Default: HTML not requested → saveHtml=False
        assert body["saveHtml"] is False

    def test_html_format_toggles_saveHtml(self, monkeypatch):
        from core.adapters.scraper.apify import ApifyAdapter
        _configure(monkeypatch)
        a = ApifyAdapter()
        body = a._build_scrape_payload({
            **_VALID_SCRAPE, "formats": ["markdown", "html"],
        })
        assert body["saveHtml"] is True

    def test_exclude_tags_maps_to_css_selector(self, monkeypatch):
        from core.adapters.scraper.apify import ApifyAdapter
        _configure(monkeypatch)
        a = ApifyAdapter()
        body = a._build_scrape_payload({
            **_VALID_SCRAPE, "exclude_tags": ["nav", "footer", "aside"],
        })
        assert body["removeElementsCssSelector"] == "nav, footer, aside"

    def test_wait_for_converts_ms_to_seconds(self, monkeypatch):
        from core.adapters.scraper.apify import ApifyAdapter
        _configure(monkeypatch)
        a = ApifyAdapter()
        # 1500 ms rounds UP to 2 s — we'd rather wait a bit
        # longer than truncate a caller-meaningful hint.
        body = a._build_scrape_payload({
            **_VALID_SCRAPE, "wait_for": 1500,
        })
        assert body["pageLoadTimeoutSecs"] == 2

    def test_wait_for_small_clamps_to_one_second(self, monkeypatch):
        from core.adapters.scraper.apify import ApifyAdapter
        _configure(monkeypatch)
        a = ApifyAdapter()
        body = a._build_scrape_payload({
            **_VALID_SCRAPE, "wait_for": 300,
        })
        # 300 ms → 1 s min (actor won't accept 0).
        assert body["pageLoadTimeoutSecs"] == 1

    def test_custom_input_passthrough_wins(self, monkeypatch):
        from core.adapters.scraper.apify import ApifyAdapter
        _configure(monkeypatch)
        a = ApifyAdapter()
        custom = {
            "foo": "bar",
            "bespoke": True,
        }
        body = a._build_scrape_payload({
            **_VALID_SCRAPE, "custom_input": custom,
        })
        # Custom-input mode: the adapter passes the dict
        # verbatim instead of synthesising a crawler config.
        assert body == custom

    def test_custom_crawler_type(self, monkeypatch):
        from core.adapters.scraper.apify import ApifyAdapter
        _configure(monkeypatch)
        a = ApifyAdapter()
        body = a._build_scrape_payload({
            **_VALID_SCRAPE, "crawler_type": "cheerio",
        })
        assert body["crawlerType"] == "cheerio"


# ── Response parsing ─────────────────────────────────────────


class TestApifyResponseParsing:
    def test_parse_happy_path(self, monkeypatch):
        from core.adapters.scraper.apify import ApifyAdapter
        _configure(monkeypatch)
        a = ApifyAdapter()
        result = a._parse_scrape_response(
            [_CANNED_APIFY_ITEM], _VALID_SCRAPE,
        )
        # Prefer loadedUrl (post-redirect) over the original URL.
        assert result["url"] == (
            "https://competitor.example.com/products/42?utm=apify"
        )
        assert result["title"] == "Widget 42 — Competitor Store"
        assert result["markdown"].startswith("# Widget 42")
        assert result["html"].startswith("<article>")
        assert result["text"] == "Widget 42 plain text body"
        assert result["status"] == 200
        assert result["metadata"]["description"] == "The best widget"

    def test_parse_status_from_crawl_httpStatusCode(self, monkeypatch):
        from core.adapters.scraper.apify import ApifyAdapter
        _configure(monkeypatch)
        a = ApifyAdapter()
        item = {**_CANNED_APIFY_ITEM, "crawl": {"httpStatusCode": 429}}
        result = a._parse_scrape_response([item], _VALID_SCRAPE)
        # Authoritative — no magic 200 fallback.
        assert result["status"] == 429

    def test_parse_missing_status_returns_zero(self, monkeypatch):
        from core.adapters.scraper.apify import ApifyAdapter
        _configure(monkeypatch)
        a = ApifyAdapter()
        item = {**_CANNED_APIFY_ITEM, "crawl": {}}
        result = a._parse_scrape_response([item], _VALID_SCRAPE)
        assert result["status"] == 0  # "unknown", not a fake 200

    def test_parse_non_array_raises(self, monkeypatch):
        from core.adapters.scraper.apify import ApifyAdapter
        _configure(monkeypatch)
        a = ApifyAdapter()
        with pytest.raises(AdapterError):
            a._parse_scrape_response(
                {"not": "an array"}, _VALID_SCRAPE,
            )

    def test_parse_empty_array_raises(self, monkeypatch):
        """Empty output from a successful run almost always
        means the target blocked the crawler — surface as a
        failure instead of a phantom success."""
        from core.adapters.scraper.apify import ApifyAdapter
        _configure(monkeypatch)
        a = ApifyAdapter()
        with pytest.raises(AdapterError) as exc_info:
            a._parse_scrape_response([], _VALID_SCRAPE)
        assert "empty" in str(exc_info.value).lower()

    def test_parse_non_dict_item_raises(self, monkeypatch):
        from core.adapters.scraper.apify import ApifyAdapter
        _configure(monkeypatch)
        a = ApifyAdapter()
        with pytest.raises(AdapterError):
            a._parse_scrape_response(["not a dict"], _VALID_SCRAPE)

    def test_parse_text_falls_back_to_markdown(self, monkeypatch):
        from core.adapters.scraper.apify import ApifyAdapter
        _configure(monkeypatch)
        a = ApifyAdapter()
        item = {**_CANNED_APIFY_ITEM, "text": "", "content": ""}
        result = a._parse_scrape_response([item], _VALID_SCRAPE)
        assert result["text"] == item["markdown"]


# ── End-to-end execute ───────────────────────────────────────


class TestApifyExecute:
    def test_execute_happy_path(self, monkeypatch):
        from core.adapters.scraper.apify import ApifyAdapter
        _configure(monkeypatch)
        a = ApifyAdapter()

        with patch.object(
            a, "_http_post", return_value=[_CANNED_APIFY_ITEM],
        ) as mock_post:
            result = a.execute(Capability.SCRAPE_PAGE, _VALID_SCRAPE)

        assert result.ok
        assert result.data["title"] == "Widget 42 — Competitor Store"
        assert result.data["status"] == 200
        # URL built with ~-separator canonicalisation.
        called_url = mock_post.call_args.args[0]
        assert "apify~website-content-crawler" in called_url
        # Bearer header threaded through (passed as kwarg by _execute).
        headers = mock_post.call_args.kwargs.get(
            "headers", mock_post.call_args.args[2]
            if len(mock_post.call_args.args) > 2 else {},
        )
        assert headers["Authorization"] == "Bearer apify-secret"

    def test_execute_with_custom_actor(self, monkeypatch):
        from core.adapters.scraper.apify import ApifyAdapter
        _configure(monkeypatch)
        a = ApifyAdapter()
        with patch.object(
            a, "_http_post", return_value=[_CANNED_APIFY_ITEM],
        ) as mock_post:
            a.execute(
                Capability.SCRAPE_PAGE,
                {**_VALID_SCRAPE, "actor": "myteam/private-scraper"},
            )
        assert "myteam~private-scraper" in mock_post.call_args.args[0]

    def test_execute_rejects_non_scrape_capability(self, monkeypatch):
        from core.adapters.scraper.apify import ApifyAdapter
        _configure(monkeypatch)
        a = ApifyAdapter()
        result = a.execute(Capability.BROWSER_SCREENSHOT, {})
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_execute_validates_url(self, monkeypatch):
        from core.adapters.scraper.apify import ApifyAdapter
        _configure(monkeypatch)
        a = ApifyAdapter()
        result = a.execute(
            Capability.SCRAPE_PAGE, {"url": "ftp://bad-scheme/page"},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)


# ── Bootstrap ────────────────────────────────────────────────


class TestScraperBootstrapIncludesApify:
    def test_register_all_adds_apify(self):
        from core.adapters.scraper.bootstrap import register_all
        status = register_all()
        assert "apify" in status
        assert "firecrawl" in status

    def test_register_all_idempotent(self):
        from core.adapters.scraper.bootstrap import register_all
        register_all()
        register_all()
        count = len([
            n for n in get_registry().names() if n == "apify"
        ])
        assert count == 1
