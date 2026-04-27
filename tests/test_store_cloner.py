"""Tests for the parallelized StoreCloner."""
import threading
import time

import pytest


def _make_cloner():
    from execution.store_cloner import StoreCloner
    return StoreCloner()


class TestExtractConfigParallel:
    def test_fetches_all_three_endpoints(self, monkeypatch):
        cloner = _make_cloner()
        calls: list[str] = []

        def fake_get(shop_url, path, h):
            calls.append(path)
            if path == "pages.json":
                return {"pages": [{"id": 1}, {"id": 2}]}
            if path == "smart_collections.json":
                return {"smart_collections": [{"id": 10}]}
            if path == "price_rules.json":
                return {"price_rules": [{"id": 100}, {"id": 101}, {"id": 102}]}
            return {}

        monkeypatch.setattr(cloner, "_api_get", fake_get)
        config = cloner._extract_config("src.myshopify.com", "tok")
        assert sorted(calls) == sorted([
            "pages.json", "smart_collections.json", "price_rules.json",
        ])
        assert len(config["pages"]) == 2
        assert len(config["collections"]) == 1
        assert len(config["discounts"]) == 3

    def test_missing_endpoint_falls_back_to_empty_list(self, monkeypatch):
        cloner = _make_cloner()

        def fake_get(shop_url, path, h):
            if path == "pages.json":
                raise RuntimeError("401 unauth")
            return {"smart_collections": [], "price_rules": []}

        monkeypatch.setattr(cloner, "_api_get", fake_get)
        config = cloner._extract_config("src.myshopify.com", "tok")
        assert config["pages"] == []
        assert config["collections"] == []
        assert config["discounts"] == []

    def test_runs_in_parallel(self, monkeypatch):
        """Three 300ms calls should finish in ~300ms parallel, not ~900ms.

        Per-call sleep bumped from 100ms → 300ms and threshold from
        0.25s → 0.60s to give slow CI runners headroom while still
        catching the regression case where parallelism breaks
        completely (sequential 0.9s > 0.6s threshold).

        Earlier 100ms / 0.25s combo was too tight: the parallel-
        completion window was only 0.15s wide, so even a moderately
        loaded CI runner could push the parallel run past 0.25s
        and trigger a flaky failure that had nothing to do with
        actual concurrency loss. The PR #46 incident.
        """
        cloner = _make_cloner()

        def slow_get(shop_url, path, h):
            time.sleep(0.3)
            if path == "pages.json":
                return {"pages": []}
            if path == "smart_collections.json":
                return {"smart_collections": []}
            return {"price_rules": []}

        monkeypatch.setattr(cloner, "_api_get", slow_get)
        t0 = time.monotonic()
        cloner._extract_config("src.myshopify.com", "tok")
        elapsed = time.monotonic() - t0
        # Sequential would be ~900ms; parallel should be ~300ms.
        # 0.60s threshold gives 300ms of jitter headroom while
        # still catching the no-parallelism regression.
        assert elapsed < 0.60, f"not parallel enough: {elapsed:.3f}s"


class TestClonePagesParallel:
    def test_skips_legal_pages(self, monkeypatch):
        cloner = _make_cloner()
        created_titles: list[str] = []
        lock = threading.Lock()

        def fake_post(shop_url, path, h, payload):
            with lock:
                created_titles.append(payload["page"]["title"])
            return {"page": {"id": len(created_titles)}}

        monkeypatch.setattr(cloner, "_api_post", fake_post)
        pages = [
            {"title": "About Us", "body_html": "<p>ok</p>"},
            {"title": "Privacy policy"},  # skip
            {"title": "FAQ", "body_html": "<p>q</p>"},
            {"title": "Return Policy"},  # skip
        ]
        count = cloner._clone_pages(pages, "target.myshopify.com", "tok")
        assert count == 2
        assert set(created_titles) == {"About Us", "FAQ"}

    def test_empty_list_returns_zero(self):
        cloner = _make_cloner()
        assert cloner._clone_pages([], "target.myshopify.com", "tok") == 0

    def test_failed_post_not_counted(self, monkeypatch):
        cloner = _make_cloner()

        def fake_post(shop_url, path, h, payload):
            if "FAQ" in payload["page"]["title"]:
                return {"error": "HTTP 500"}  # failure
            return {"page": {"id": 1}}

        monkeypatch.setattr(cloner, "_api_post", fake_post)
        pages = [{"title": "About"}, {"title": "FAQ"}, {"title": "Blog"}]
        assert cloner._clone_pages(pages, "t.myshopify.com", "tok") == 2

    def test_runs_in_parallel(self, monkeypatch):
        # Same flake-resilience treatment as the extract_config
        # test above: bump per-call sleep + threshold so slow CI
        # runners don't trip the assertion when parallelism is
        # actually working.
        cloner = _make_cloner()

        def slow_post(shop_url, path, h, payload):
            time.sleep(0.3)
            return {"page": {"id": 1}}

        monkeypatch.setattr(cloner, "_api_post", slow_post)
        pages = [{"title": f"p{i}"} for i in range(5)]  # max_workers=5
        t0 = time.monotonic()
        count = cloner._clone_pages(pages, "t.myshopify.com", "tok")
        elapsed = time.monotonic() - t0
        assert count == 5
        # Sequential: 1500ms. Parallel with 5 workers: ~300ms.
        # 0.60s threshold catches the regression while tolerating
        # ~300ms of CI jitter.
        assert elapsed < 0.60, f"not parallel enough: {elapsed:.3f}s"


class TestCloneDiscountsParallel:
    def test_creates_rule_and_discount_code(self, monkeypatch):
        cloner = _make_cloner()
        calls: list[str] = []
        lock = threading.Lock()

        def fake_post(shop_url, path, h, payload):
            with lock:
                calls.append(path)
            if path == "price_rules.json":
                return {"price_rule": {"id": 42}}
            return {"discount_code": {"id": 1}}

        monkeypatch.setattr(cloner, "_api_post", fake_post)
        count = cloner._clone_discounts(
            [{"title": "SALE10", "value": "-10"}],
            "t.myshopify.com", "tok",
        )
        assert count == 1
        assert "price_rules.json" in calls
        assert any("discount_codes.json" in c for c in calls)

    def test_rule_failure_skips_discount_code(self, monkeypatch):
        cloner = _make_cloner()
        calls: list[str] = []

        def fake_post(shop_url, path, h, payload):
            calls.append(path)
            if path == "price_rules.json":
                return {"error": "HTTP 422"}
            return {"discount_code": {"id": 1}}

        monkeypatch.setattr(cloner, "_api_post", fake_post)
        count = cloner._clone_discounts(
            [{"title": "BAD"}], "t.myshopify.com", "tok",
        )
        assert count == 0
        # Should not have attempted the discount_codes endpoint
        assert not any("discount_codes" in c for c in calls)

    def test_empty_list(self):
        cloner = _make_cloner()
        assert cloner._clone_discounts([], "t.myshopify.com", "tok") == 0


class TestCloneFlow:
    def test_clone_end_to_end(self, monkeypatch):
        """Smoke test of clone() with mocked HTTP."""
        cloner = _make_cloner()

        def fake_get(shop_url, path, h):
            responses = {
                "pages.json": {"pages": [{"title": "About"}, {"title": "FAQ"}]},
                "smart_collections.json": {"smart_collections": [{"id": 1}]},
                "price_rules.json": {"price_rules": [{"title": "SALE"}]},
            }
            return responses.get(path, {})

        def fake_post(shop_url, path, h, payload):
            if path == "price_rules.json":
                return {"price_rule": {"id": 42}}
            if "discount_codes" in path:
                return {"discount_code": {"id": 1}}
            return {"page": {"id": 99}}

        monkeypatch.setattr(cloner, "_api_get", fake_get)
        monkeypatch.setattr(cloner, "_api_post", fake_post)

        result = cloner.clone(
            source_url="src.myshopify.com", source_token="s",
            target_url="tgt.myshopify.com", target_token="t",
        )
        assert result["status"] == "cloned"
        steps = result["results"]["steps"]
        # Extract step should show 2 pages and 1 discount
        extract = next(s for s in steps if "extract" in s)
        assert extract["pages"] == 2
        assert extract["discounts"] == 1
        # Pages clone step — both non-legal titles created
        pages_step = next(s for s in steps if "pages" in s and "extract" not in s)
        assert pages_step["pages"] == 2
        # Discount clone step
        discounts_step = next(s for s in steps if "discounts" in s and "extract" not in s)
        assert discounts_step["discounts"] == 1


class TestGetStoreCloner:
    def test_returns_singleton(self):
        from execution import store_cloner as mod
        mod._instance = None
        a = mod.get_store_cloner()
        b = mod.get_store_cloner()
        assert a is b
