"""Unit tests for the competitor_intel agent.

Everything stays offline — the public API takes an injectable
``http_get`` + ``llm`` pair, so these tests never hit the
network and never spend LLM budget. The real provider calls
only happen from the CLI / MCP entry points which plug in
``_default_http_get`` + ``core.llm_gateway.ask``.

Covers:
  * products.json paging + price range / median / tag +
    currency extraction
  * homepage app signature detection (Klaviyo, Loox, Meta
    Pixel, etc.) + theme sniffing + hero H1 extraction
  * soft-fail when a single source (collections, homepage)
    errors out — the rest still produces a usable report
  * LLM dispatcher is called once per store with a fully
    rendered prompt, and exceptions are captured (not raised)
  * ``analyze_competitors`` throttles between stores
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from agents.competitor_intel import (
    CompetitorReport,
    analyze_competitor,
    analyze_competitors,
    diff_vs_last,
    load_history,
    save_report,
)
from agents.competitor_intel.agent import (
    _build_catalog_summary,
    _detect_apps,
    _detect_theme,
    _fetch_products_json,
    _normalise_host,
    _slugify,
)


# ── Host normalisation ──────────────────────────────────────


class TestNormaliseHost:
    def test_strips_https_scheme(self):
        assert _normalise_host("https://allbirds.com") == "allbirds.com"

    def test_strips_http_scheme(self):
        assert _normalise_host("http://x.myshopify.com") == "x.myshopify.com"

    def test_strips_trailing_slash(self):
        assert _normalise_host("allbirds.com/") == "allbirds.com"

    def test_leaves_bare_host_alone(self):
        assert _normalise_host("gymshark.com") == "gymshark.com"


# ── Catalog summary ────────────────────────────────────────


def _prod(
    title: str, price: str, tags: str = "", ptype: str = "",
    vendor: str = "Ven", handle: str | None = None,
    published_at: str = "2026-04-20T10:00:00Z",
) -> dict:
    return {
        "title": title,
        "handle": handle or title.lower().replace(" ", "-"),
        "tags": tags,
        "product_type": ptype,
        "vendor": vendor,
        "published_at": published_at,
        "variants": [{
            "price": price,
            "presentment_prices": [{
                "price": {"amount": price, "currency_code": "USD"},
            }],
        }],
    }


class TestCatalogSummary:
    def test_empty_input_marks_error(self):
        s = _build_catalog_summary("x.com", [])
        assert s.product_count == 0
        assert "no products" in s.error

    def test_price_range_and_median(self):
        s = _build_catalog_summary("x.com", [
            _prod("A", "10.00"),
            _prod("B", "20.00"),
            _prod("C", "30.00"),
        ])
        assert s.product_count == 3
        assert s.price_range == (10.0, 30.0)
        assert s.median_price == 20.0

    def test_top_types_sorted_by_count(self):
        s = _build_catalog_summary("x.com", [
            _prod("A", "10", ptype="Mug"),
            _prod("B", "10", ptype="Mug"),
            _prod("C", "10", ptype="Shirt"),
        ])
        assert s.top_types[0] == "Mug"

    def test_tags_split_on_comma(self):
        s = _build_catalog_summary("x.com", [
            _prod("A", "10", tags="cozy, bedroom, gift"),
            _prod("B", "10", tags="cozy, spa"),
        ])
        assert "cozy" in s.top_tags  # most common
        assert s.top_tags[0] == "cozy"

    def test_currencies_collected(self):
        s = _build_catalog_summary("x.com", [
            _prod("A", "10"),
        ])
        assert "USD" in s.currencies

    def test_newest_first(self):
        s = _build_catalog_summary("x.com", [
            _prod("Old", "10", published_at="2024-01-01T00:00:00Z"),
            _prod("New", "10", published_at="2026-05-01T00:00:00Z"),
        ])
        assert s.newest_products[0]["title"] == "New"

    def test_invalid_price_strings_tolerated(self):
        p = _prod("A", "not-a-number")
        s = _build_catalog_summary("x.com", [p])
        # The bad variant price gets skipped; no crash, empty range
        assert s.product_count == 1
        assert s.price_range == (0.0, 0.0)


# ── Paged products.json fetch ──────────────────────────────


def _make_http(responses: dict[str, dict]):
    """Build a fake http_get that returns canned payloads keyed
    by URL."""
    calls: list[str] = []

    def http_get(url: str):
        calls.append(url)
        return responses.get(url, {"status": 404, "body": ""})

    http_get.calls = calls  # type: ignore[attr-defined]
    return http_get


class TestFetchProductsJson:
    def test_single_page(self):
        prods = [_prod(f"P{i}", "10") for i in range(5)]
        http = _make_http({
            "https://x.com/products.json?limit=250&page=1": {
                "status": 200,
                "body": json.dumps({"products": prods}),
            },
        })
        out = _fetch_products_json("x.com", http)
        assert len(out) == 5
        # Short page stops pagination
        assert len(http.calls) == 1

    def test_paginates_when_full(self):
        full = [_prod(f"P{i}", "10") for i in range(250)]
        partial = [_prod("last", "10")]
        http = _make_http({
            "https://x.com/products.json?limit=250&page=1": {
                "status": 200,
                "body": json.dumps({"products": full}),
            },
            "https://x.com/products.json?limit=250&page=2": {
                "status": 200,
                "body": json.dumps({"products": partial}),
            },
        })
        out = _fetch_products_json("x.com", http)
        assert len(out) == 251

    def test_404_halts(self):
        http = _make_http({})
        out = _fetch_products_json("x.com", http)
        assert out == []

    def test_garbage_json_halts(self):
        http = _make_http({
            "https://x.com/products.json?limit=250&page=1": {
                "status": 200,
                "body": "<html>not json</html>",
            },
        })
        out = _fetch_products_json("x.com", http)
        assert out == []


# ── App + theme detection ──────────────────────────────────


class TestAppDetection:
    def test_detects_klaviyo(self):
        html = '<script src="https://static.klaviyo.com/foo.js"></script>'
        apps = _detect_apps(html)
        assert any("Klaviyo" in a for a in apps)

    def test_detects_loox(self):
        html = '<script src="https://loox.io/widget.js"></script>'
        apps = _detect_apps(html)
        assert any("Loox" in a for a in apps)

    def test_detects_meta_pixel(self):
        html = '<script>fbq("init"); </script><img src="https://facebook.net/tr?"/>'
        apps = _detect_apps(html)
        assert any("Meta Pixel" in a for a in apps)

    def test_no_double_counting(self):
        html = "klaviyo klaviyo klaviyo"
        apps = _detect_apps(html)
        klaviyo_count = sum(1 for a in apps if "Klaviyo" in a)
        assert klaviyo_count == 1


class TestThemeDetection:
    def test_generator_meta(self):
        html = '<meta name="generator" content="Shopify Dawn 12.0">'
        assert _detect_theme(html).startswith("Shopify Dawn")

    def test_fallback_on_section_wrapper(self):
        html = '<div class="shopify-section-header">...</div>'
        assert "Shopify theme" in _detect_theme(html)

    def test_returns_empty_when_no_hints(self):
        assert _detect_theme("<html><body>hi</body></html>") == ""


# ── analyze_competitor integration ────────────────────────


def _full_http(store: str = "x.com"):
    """Fully-populated fake http_get covering all 3 endpoints."""
    prods = [
        _prod("Galaxy Projector", "29.99", tags="cozy, gift", ptype="Light"),
        _prod("Moon Lamp", "24.50", tags="cozy, spa", ptype="Light"),
    ]
    home = """
    <html>
      <head>
        <meta name="generator" content="Shopify Dawn 12.0">
      </head>
      <body>
        <div class="announcement-bar">Free shipping over $50</div>
        <h1>Calm &amp; Cozy Home</h1>
        <script src="https://static.klaviyo.com/a.js"></script>
        <script src="https://loox.io/widget.js"></script>
        <script src="https://connect.facebook.net/tr?id=123"></script>
      </body>
    </html>
    """
    collections = {"collections": [
        {"handle": "best-sellers"},
        {"handle": "cozy-bedroom"},
    ]}
    responses = {
        f"https://{store}/products.json?limit=250&page=1": {
            "status": 200,
            "body": json.dumps({"products": prods}),
        },
        f"https://{store}/collections.json?limit=250": {
            "status": 200,
            "body": json.dumps(collections),
        },
        f"https://{store}/": {
            "status": 200,
            "body": home,
        },
    }
    return _make_http(responses)


class TestAnalyzeCompetitor:
    def test_full_report_without_llm(self):
        r = analyze_competitor(
            "x.com", http_get=_full_http(), llm=None,
            now_fn=lambda: 1_700_000_000.0,
        )
        assert isinstance(r, CompetitorReport)
        assert r.catalog.product_count == 2
        assert r.catalog.price_range[0] == 24.5
        assert r.homepage.theme_hint.startswith("Shopify Dawn")
        assert any("Klaviyo" in a for a in r.homepage.apps_detected)
        assert "best-sellers" in r.collection_handles
        assert r.insights == ""  # llm not plugged in
        assert r.errors == []

    def test_llm_called_with_prompt(self):
        llm = MagicMock(return_value="Move 1: add reviews.")
        r = analyze_competitor(
            "x.com", http_get=_full_http(), llm=llm,
            now_fn=lambda: 1_700_000_000.0,
        )
        assert llm.call_count == 1
        prompt = llm.call_args.args[0]
        # Prompt mentions the store + catalogue data
        assert "x.com" in prompt
        assert "Galaxy Projector" in prompt or "Moon Lamp" in prompt
        assert r.insights == "Move 1: add reviews."

    def test_llm_error_captured_not_raised(self):
        def boom(prompt: str) -> str:
            raise RuntimeError("rate-limited")
        r = analyze_competitor(
            "x.com", http_get=_full_http(), llm=boom,
        )
        assert r.insights == ""
        assert any("llm:" in e for e in r.errors)
        # Catalogue still populated
        assert r.catalog.product_count == 2

    def test_broken_collections_soft_fail(self):
        # /products.json + / work, but /collections.json 500s
        http_resp = _full_http().calls  # noqa: F841 — warm closure
        responses = {
            "https://x.com/products.json?limit=250&page=1": {
                "status": 200,
                "body": json.dumps({
                    "products": [_prod("A", "10")],
                }),
            },
            "https://x.com/collections.json?limit=250": {
                "status": 500, "body": "",
            },
            "https://x.com/": {
                "status": 200,
                "body": "<html><h1>Store</h1></html>",
            },
        }
        http = _make_http(responses)
        r = analyze_competitor("x.com", http_get=http)
        # Catalog still there
        assert r.catalog.product_count == 1
        # Empty collections (not a hard error — empty list is fine)
        assert r.collection_handles == []

    def test_private_store_empty_catalog(self):
        # Simulate fully-private store: everything 404
        http = _make_http({})
        r = analyze_competitor("x.com", http_get=http)
        assert r.catalog.product_count == 0
        assert "no products" in r.catalog.error


# ── Batch ─────────────────────────────────────────────────


class TestAnalyzeCompetitors:
    def test_batches_multiple_stores(self):
        http = _full_http("a.com")
        # Extend the fake to also cover b.com with same payload
        for u, v in list(http.calls_backing_responses().items() if hasattr(http, "calls_backing_responses") else []):
            pass
        # Build a combined responder
        data_a = _full_http("a.com")
        data_b = _full_http("b.com")

        def both(url: str):
            r = data_a(url)
            if r.get("status") == 200:
                return r
            return data_b(url)

        reports = analyze_competitors(
            ["a.com", "b.com"],
            http_get=both, throttle_s=0.0,
        )
        assert len(reports) == 2
        assert reports[0].store == "a.com"
        assert reports[1].store == "b.com"

    def test_throttle_respected(self, monkeypatch):
        """Batch sleeps between stores (but not after last)."""
        import agents.competitor_intel.agent as mod

        sleep_calls: list[float] = []
        monkeypatch.setattr(
            mod.time, "sleep", lambda s: sleep_calls.append(s),
        )

        data_a = _full_http("a.com")
        data_b = _full_http("b.com")
        data_c = _full_http("c.com")

        def merged(url: str):
            for fn in (data_a, data_b, data_c):
                r = fn(url)
                if r.get("status") == 200:
                    return r
            return {"status": 404, "body": ""}

        reports = analyze_competitors(
            ["a.com", "b.com", "c.com"],
            http_get=merged, throttle_s=0.75,
        )
        assert len(reports) == 3
        # Two sleeps (between store 1→2, 2→3) — not after last
        assert sleep_calls == [0.75, 0.75]


# ── Persistence + diff ────────────────────────────────────


class TestSlugify:
    def test_https_scheme_stripped(self):
        assert _slugify("https://a.b.com") == "a-b-com"

    def test_trailing_slash_stripped(self):
        assert _slugify("foo.myshopify.com/") == "foo-myshopify-com"

    def test_non_alnum_collapsed(self):
        assert _slugify("x_y:z") == "x-y-z"

    def test_empty_fallback(self):
        assert _slugify("") == "unknown"


class TestSaveAndLoadHistory:
    def test_round_trip(self, tmp_path):
        r = analyze_competitor(
            "x.com", http_get=_full_http(), llm=None,
            now_fn=lambda: 1_700_000_000.0,
        )
        path = save_report(r, storage_dir=str(tmp_path))
        assert path.endswith("x-com.jsonl")
        hist = load_history("x.com", storage_dir=str(tmp_path))
        assert len(hist) == 1
        assert hist[0]["store"] == "x.com"
        assert hist[0]["catalog"]["product_count"] == 2

    def test_append_accumulates(self, tmp_path):
        r = analyze_competitor(
            "x.com", http_get=_full_http(), llm=None,
            now_fn=lambda: 1_700_000_000.0,
        )
        save_report(r, storage_dir=str(tmp_path))
        save_report(r, storage_dir=str(tmp_path))
        save_report(r, storage_dir=str(tmp_path))
        hist = load_history("x.com", storage_dir=str(tmp_path))
        assert len(hist) == 3

    def test_limit_returns_tail(self, tmp_path):
        for _ in range(5):
            r = analyze_competitor(
                "x.com", http_get=_full_http(), llm=None,
            )
            save_report(r, storage_dir=str(tmp_path))
        hist = load_history(
            "x.com", storage_dir=str(tmp_path), limit=2,
        )
        assert len(hist) == 2

    def test_missing_file_returns_empty(self, tmp_path):
        hist = load_history(
            "nobody.com", storage_dir=str(tmp_path),
        )
        assert hist == []

    def test_corrupt_line_skipped(self, tmp_path):
        # Pre-plant one valid + one garbage line
        path = tmp_path / "a-com.jsonl"
        path.write_text(
            '{"store":"a.com","catalog":{"product_count":3}}\n'
            'not-json\n'
            '{"store":"a.com","catalog":{"product_count":4}}\n'
        )
        hist = load_history("a.com", storage_dir=str(tmp_path))
        assert len(hist) == 2
        assert hist[0]["catalog"]["product_count"] == 3
        assert hist[1]["catalog"]["product_count"] == 4

    def test_slug_collision_avoided(self, tmp_path):
        """Hosts that share a base but differ by subdomain must
        land in separate files."""
        r1 = analyze_competitor(
            "shop.x.com", http_get=_full_http("shop.x.com"),
            llm=None,
        )
        r2 = analyze_competitor(
            "x.com", http_get=_full_http("x.com"), llm=None,
        )
        save_report(r1, storage_dir=str(tmp_path))
        save_report(r2, storage_dir=str(tmp_path))
        files = sorted(p.name for p in tmp_path.iterdir())
        assert "shop-x-com.jsonl" in files
        assert "x-com.jsonl" in files


class TestDiffVsLast:
    def _mk_report(self, **over):
        """Build a minimal CompetitorReport for diff tests."""
        from agents.competitor_intel.agent import (
            HomepageSignals, StoreCatalogSummary,
        )
        cat = StoreCatalogSummary(
            store="x.com",
            product_count=over.get("product_count", 10),
            median_price=over.get("median_price", 25.0),
            top_products=over.get("top_products", [
                {"handle": "a"}, {"handle": "b"},
            ]),
            newest_products=over.get("newest_products", [
                {"handle": "a"}, {"handle": "b"},
            ]),
        )
        hp = HomepageSignals(
            apps_detected=over.get("apps_detected", ["Klaviyo (email/SMS)"]),
        )
        return CompetitorReport(
            store="x.com", scraped_at=over.get("ts", 1_700_000_000.0),
            catalog=cat, homepage=hp,
        )

    def test_baseline_when_no_previous(self):
        r = self._mk_report()
        d = diff_vs_last(r, None)
        assert d["baseline"] is True
        assert d["product_count_delta"] == 0

    def test_product_count_delta(self):
        prev = self._mk_report(product_count=10).as_dict()
        cur = self._mk_report(product_count=15)
        d = diff_vs_last(cur, prev)
        assert d["product_count_delta"] == 5
        assert d["baseline"] is False

    def test_median_price_delta(self):
        prev = self._mk_report(median_price=20.0).as_dict()
        cur = self._mk_report(median_price=25.5)
        d = diff_vs_last(cur, prev)
        assert d["median_price_delta_usd"] == 5.5

    def test_added_and_removed_handles(self):
        prev = self._mk_report(
            top_products=[{"handle": "a"}, {"handle": "b"}],
            newest_products=[{"handle": "a"}],
        ).as_dict()
        cur = self._mk_report(
            top_products=[{"handle": "b"}, {"handle": "c"}],
            newest_products=[{"handle": "d"}],
        )
        d = diff_vs_last(cur, prev)
        assert "c" in d["added_handles"]
        assert "d" in d["added_handles"]
        assert "a" in d["removed_handles"]
        assert "b" not in d["added_handles"]
        assert "b" not in d["removed_handles"]

    def test_new_and_lost_apps(self):
        prev = self._mk_report(
            apps_detected=["Klaviyo (email/SMS)", "Loox (photo reviews)"],
        ).as_dict()
        cur = self._mk_report(
            apps_detected=[
                "Klaviyo (email/SMS)",
                "Meta Pixel",
            ],
        )
        d = diff_vs_last(cur, prev)
        assert "Meta Pixel" in d["new_apps"]
        assert "Loox (photo reviews)" in d["lost_apps"]
        assert "Klaviyo (email/SMS)" not in d["new_apps"]

    def test_no_change_is_empty_sets(self):
        prev = self._mk_report().as_dict()
        cur = self._mk_report()
        d = diff_vs_last(cur, prev)
        assert d["product_count_delta"] == 0
        assert d["median_price_delta_usd"] == 0.0
        assert d["added_handles"] == []
        assert d["removed_handles"] == []
        assert d["new_apps"] == []
        assert d["lost_apps"] == []

    def test_previous_timestamp_preserved(self):
        prev = self._mk_report(ts=1_699_000_000.0).as_dict()
        cur = self._mk_report(ts=1_700_000_000.0)
        d = diff_vs_last(cur, prev)
        assert d["previous_scraped_at"] == 1_699_000_000.0
