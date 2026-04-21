"""StoreConfigurator pages feature tests (Phase 1a).

`_setup_pages` creates About, Contact, and FAQ pages on a
fresh Shopify store. These are legal/trust-signal pages
every paid-ads storefront needs. Tests lock:
  * idempotency on handle (skip existing)
  * dry-run preview shape
  * error isolation per page
  * niche-aware tone in body_html
"""
from __future__ import annotations


def _make(dry_run: bool = False):
    from execution.store_configurator import StoreConfigurator
    return StoreConfigurator(dry_run=dry_run)


def _install_fake_client(
    monkeypatch, responses=None, track_calls=None,
):
    responses = responses or {}
    track_calls = (
        track_calls if track_calls is not None else []
    )

    class FakeClient:
        def __init__(self, shop_url, token, **kw):
            self.shop_url = shop_url

        def get(self, path, *, params=None):
            track_calls.append(("GET", path, params))
            return responses.get(f"GET {path}", {})

        def post(self, path, *, json=None):
            track_calls.append(("POST", path, json))
            return responses.get(f"POST {path}", {})

        def put(self, path, *, json=None):
            track_calls.append(("PUT", path, json))
            return responses.get(f"PUT {path}", {})

        def delete(self, path):
            track_calls.append(("DELETE", path, None))
            return responses.get(f"DELETE {path}", {})

    monkeypatch.setattr(
        "execution.store_configurator.ShopifyClient",
        FakeClient,
    )
    return track_calls


class TestPagesFeatureEnabled:
    def test_pages_in_all_features(self):
        from execution.store_configurator import ALL_FEATURES
        assert "pages" in ALL_FEATURES

    def test_pages_runs_when_default(self, monkeypatch):
        calls = _install_fake_client(monkeypatch)
        c = _make(dry_run=True)
        result = c.configure(
            "x.myshopify.com", "tok",
            niche="home", store_name="Cozy Shop",
        )
        assert "pages" in result["results"]


class TestPagesDryRun:
    def test_creates_about_contact_faq(self, monkeypatch):
        _install_fake_client(monkeypatch)
        c = _make(dry_run=True)
        result = c.configure(
            "x.myshopify.com", "tok",
            niche="beauty", store_name="Glow Co",
            features=["pages"],
        )
        pages = result["results"]["pages"]
        assert pages["status"] == "dry_run"
        assert set(pages["created"]) == {
            "about", "contact", "faq",
        }
        assert pages["skipped"] == []
        assert pages["errors"] == []

    def test_dry_run_records_plan_entries(self, monkeypatch):
        _install_fake_client(monkeypatch)
        c = _make(dry_run=True)
        result = c.configure(
            "x.myshopify.com", "tok",
            niche="general",
            features=["pages"],
        )
        plan = result["plan"]
        create_page_entries = [
            e for e in plan
            if e.get("action") == "create_page"
        ]
        assert len(create_page_entries) == 3
        handles = {e["handle"] for e in create_page_entries}
        assert handles == {"about", "contact", "faq"}


class TestPagesLive:
    def test_posts_to_pages_json(self, monkeypatch):
        calls = _install_fake_client(
            monkeypatch,
            responses={
                "GET pages.json": {"pages": []},
                "POST pages.json": {
                    "page": {"id": 1, "handle": "about"},
                },
            },
        )
        c = _make(dry_run=False)
        result = c.configure(
            "x.myshopify.com", "tok",
            niche="tech", store_name="Gadget Hub",
            features=["pages"],
        )
        posts = [
            call for call in calls
            if call[0] == "POST"
            and call[1] == "pages.json"
        ]
        assert len(posts) == 3
        for _, _, body in posts:
            page = body["page"]
            assert page["published"] is True
            assert page["title"]
            assert page["body_html"]
            assert page["handle"] in {
                "about", "contact", "faq",
            }
        pages_out = result["results"]["pages"]
        assert pages_out["status"] == "success"

    def test_skips_existing_handles_idempotently(
        self, monkeypatch,
    ):
        calls = _install_fake_client(
            monkeypatch,
            responses={
                "GET pages.json": {
                    "pages": [
                        {"id": 99, "handle": "about"},
                        {"id": 100, "handle": "contact"},
                    ],
                },
                "POST pages.json": {
                    "page": {"id": 101, "handle": "faq"},
                },
            },
        )
        c = _make(dry_run=False)
        result = c.configure(
            "x.myshopify.com", "tok",
            niche="general",
            features=["pages"],
        )
        pages_out = result["results"]["pages"]
        assert "faq" in pages_out["created"]
        assert set(pages_out["skipped"]) == {
            "about", "contact",
        }
        # Only 1 POST (for FAQ)
        posts = [
            c for c in calls
            if c[0] == "POST" and c[1] == "pages.json"
        ]
        assert len(posts) == 1

    def test_partial_failure_recorded(self, monkeypatch):
        """One page API error doesn't abort the rest."""
        call_count = {"n": 0}

        responses = {
            "GET pages.json": {"pages": []},
        }

        def fake_post_response(path, *, json=None):
            call_count["n"] += 1
            if call_count["n"] == 2:
                return {"error": "rate limited"}
            return {
                "page": {
                    "id": call_count["n"],
                    "handle": json["page"]["handle"],
                },
            }

        class FakeClient:
            def __init__(self, *a, **kw): pass
            def get(self, path, *, params=None):
                return {"pages": []}
            def post(self, path, *, json=None):
                return fake_post_response(path, json=json)
            def put(self, path, *, json=None):
                return {}
            def delete(self, path):
                return {}

        monkeypatch.setattr(
            "execution.store_configurator.ShopifyClient",
            FakeClient,
        )
        c = _make(dry_run=False)
        result = c.configure(
            "x.myshopify.com", "tok",
            niche="general",
            features=["pages"],
        )
        pages_out = result["results"]["pages"]
        assert pages_out["status"] == "partial"
        assert len(pages_out["errors"]) == 1
        assert "rate limited" in (
            pages_out["errors"][0]["error"]
        )
        # At least one page succeeded
        assert pages_out["created"]


class TestPageTemplatesNicheAware:
    def test_niche_tone_in_body(self):
        from execution.store_configurator import (
            _page_templates,
        )
        fashion_pages = _page_templates(
            "fashion", "Vogue Street",
        )
        home_pages = _page_templates(
            "home", "Cozy Corner",
        )
        # About page body differs by niche (tone word)
        fashion_about = next(
            p for p in fashion_pages if p["handle"] == "about"
        )
        home_about = next(
            p for p in home_pages if p["handle"] == "about"
        )
        assert "confident" in fashion_about["body_html"]
        assert "cozy" in home_about["body_html"]

    def test_unknown_niche_falls_back_to_general(self):
        from execution.store_configurator import (
            _page_templates,
        )
        pages = _page_templates("zzzznotreal", "Shop X")
        about = next(
            p for p in pages if p["handle"] == "about"
        )
        assert "friendly" in about["body_html"]

    def test_store_name_appears_in_title(self):
        from execution.store_configurator import (
            _page_templates,
        )
        pages = _page_templates("general", "Acme Test")
        about = next(
            p for p in pages if p["handle"] == "about"
        )
        assert "Acme Test" in about["title"]
        assert "Acme Test" in about["body_html"]

    def test_empty_store_name_falls_back(self):
        from execution.store_configurator import (
            _page_templates,
        )
        pages = _page_templates("general", "")
        # No empty "About " — falls back to "Our Store"
        about = next(
            p for p in pages if p["handle"] == "about"
        )
        assert "Our Store" in about["title"]
