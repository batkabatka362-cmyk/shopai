"""Regression tests for the reviews adapter family.

Wave 1 extension — Judge.me only.

Real HTTP calls are forbidden — every test patches the
adapter's ``_http_get`` helper so the suite stays hermetic.

Coverage matrix:

  * Capability enum exposes PRODUCT_REVIEWS_FETCH
  * ReviewsBaseAdapter validates inputs (shop_domain required +
    FQDN shape, per_page 1-100, page >= 1, rating_min 1-5) and
    rejects unknown capabilities
  * JudgeMeAdapter
        - registry metadata (name, category, capabilities,
          priority, cost)
        - is_configured() requires JUDGEME_API_TOKEN
        - _fetch_url points at /api/v1/reviews
        - _auth_params contains api_token
        - query string carries shop_domain + optional filters
        - parse extracts reviews[] normalised shape
        - rating_min post-filters the result even when vendor
          returns every review
        - verified_only post-filters unverified reviews
        - parse non-dict / missing reviews raises AdapterError
        - happy path captures reviews list + metadata
        - HTTP error mapping (auth, rate limit)
  * Bootstrap
        - register_all adds the adapter, idempotent
        - status map reflects is_configured
  * SmartRouter
        - routes PRODUCT_REVIEWS_FETCH to judgeme when configured
        - raises NoAdapterAvailable when unconfigured
        - end-to-end execute() succeeds and the metrics collector
          captures the outcome
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
    """Clear Judge.me env + every adapter singleton between tests."""
    for var in (
        "JUDGEME_API_TOKEN",
        "IMAGEKIT_PUBLIC_KEY",
        "IMAGEKIT_PRIVATE_KEY",
        "FIRECRAWL_API_KEY",
        "BREVO_API_KEY",
        "RESEND_API_KEY",
        "OPENAI_API_KEY",
        "TWILIO_ACCOUNT_SID",
        "TWILIO_AUTH_TOKEN",
        "TWILIO_FROM_NUMBER",
        "DEEPL_API_KEY",
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


def _configure_judgeme(monkeypatch) -> str:
    token = "judgeme_token_xxxxxxxx"
    monkeypatch.setenv("JUDGEME_API_TOKEN", token)
    get_config().reload()
    return token


_VALID_FETCH = {
    "shop_domain": "demo.myshopify.com",
    "per_page": 5,
    "page": 1,
}


def _mock_judgeme_response(reviews: list[dict]) -> dict:
    return {
        "current_page": 1,
        "per_page": 10,
        "reviews": reviews,
    }


# ── Capability enum ─────────────────────────────────────────


class TestReviewsCapabilities:
    def test_product_reviews_fetch_capability_exists(self):
        assert Capability("product_reviews_fetch") is (
            Capability.PRODUCT_REVIEWS_FETCH
        )


# ── ReviewsBaseAdapter validation ───────────────────────────


class TestReviewsBaseValidation:
    def test_shop_domain_required(self, monkeypatch):
        from core.adapters.reviews.judgeme import JudgeMeAdapter
        _configure_judgeme(monkeypatch)
        a = JudgeMeAdapter()
        result = a.execute(Capability.PRODUCT_REVIEWS_FETCH, {})
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)
        assert "shop_domain" in result.error.reason

    def test_shop_domain_must_be_fqdn(self, monkeypatch):
        from core.adapters.reviews.judgeme import JudgeMeAdapter
        _configure_judgeme(monkeypatch)
        a = JudgeMeAdapter()
        result = a.execute(
            Capability.PRODUCT_REVIEWS_FETCH,
            {"shop_domain": "localhost"},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_per_page_upper_bound(self, monkeypatch):
        from core.adapters.reviews.judgeme import JudgeMeAdapter
        _configure_judgeme(monkeypatch)
        a = JudgeMeAdapter()
        result = a.execute(
            Capability.PRODUCT_REVIEWS_FETCH,
            {"shop_domain": "x.myshopify.com", "per_page": 101},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_per_page_lower_bound(self, monkeypatch):
        from core.adapters.reviews.judgeme import JudgeMeAdapter
        _configure_judgeme(monkeypatch)
        a = JudgeMeAdapter()
        result = a.execute(
            Capability.PRODUCT_REVIEWS_FETCH,
            {"shop_domain": "x.myshopify.com", "per_page": 0},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_per_page_non_numeric_rejected(self, monkeypatch):
        from core.adapters.reviews.judgeme import JudgeMeAdapter
        _configure_judgeme(monkeypatch)
        a = JudgeMeAdapter()
        result = a.execute(
            Capability.PRODUCT_REVIEWS_FETCH,
            {"shop_domain": "x.myshopify.com", "per_page": "many"},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_page_must_be_positive(self, monkeypatch):
        from core.adapters.reviews.judgeme import JudgeMeAdapter
        _configure_judgeme(monkeypatch)
        a = JudgeMeAdapter()
        result = a.execute(
            Capability.PRODUCT_REVIEWS_FETCH,
            {"shop_domain": "x.myshopify.com", "page": 0},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_rating_min_range(self, monkeypatch):
        from core.adapters.reviews.judgeme import JudgeMeAdapter
        _configure_judgeme(monkeypatch)
        a = JudgeMeAdapter()
        result = a.execute(
            Capability.PRODUCT_REVIEWS_FETCH,
            {"shop_domain": "x.myshopify.com", "rating_min": 9},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_unknown_capability_returns_validation_error(self, monkeypatch):
        from core.adapters.reviews.judgeme import JudgeMeAdapter
        _configure_judgeme(monkeypatch)
        a = JudgeMeAdapter()
        result = a.execute(Capability.SEND_EMAIL_TRANSACTIONAL, {})
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)


# ── JudgeMeAdapter ──────────────────────────────────────────


class TestJudgeMeAdapter:
    def test_metadata(self):
        from core.adapters.reviews.judgeme import JudgeMeAdapter
        a = JudgeMeAdapter()
        assert a.name == "judgeme"
        assert a.category == AdapterCategory.SHOPIFY_APP
        assert Capability.PRODUCT_REVIEWS_FETCH in a.capabilities
        assert a.priority == 80
        assert a.cost_per_call == 0.0

    def test_unconfigured_without_token(self):
        from core.adapters.reviews.judgeme import JudgeMeAdapter
        assert not JudgeMeAdapter().is_configured()

    def test_configured_with_token(self, monkeypatch):
        from core.adapters.reviews.judgeme import JudgeMeAdapter
        _configure_judgeme(monkeypatch)
        assert JudgeMeAdapter().is_configured()

    def test_fetch_url(self):
        from core.adapters.reviews.judgeme import JudgeMeAdapter
        a = JudgeMeAdapter()
        assert a._fetch_url() == "https://judge.me/api/v1/reviews"

    def test_auth_params_include_token(self, monkeypatch):
        from core.adapters.reviews.judgeme import JudgeMeAdapter
        token = _configure_judgeme(monkeypatch)
        a = JudgeMeAdapter()
        assert ("api_token", token) in a._auth_params()

    def test_query_basic(self, monkeypatch):
        from core.adapters.reviews.judgeme import JudgeMeAdapter
        _configure_judgeme(monkeypatch)
        a = JudgeMeAdapter()
        query = a._build_fetch_params(
            {"shop_domain": "demo.myshopify.com"},
        )
        assert ("shop_domain", "demo.myshopify.com") in query

    def test_query_with_product_filter(self, monkeypatch):
        from core.adapters.reviews.judgeme import JudgeMeAdapter
        _configure_judgeme(monkeypatch)
        a = JudgeMeAdapter()
        query = a._build_fetch_params(
            {
                "shop_domain": "demo.myshopify.com",
                "product_id": 123456,
                "product_handle": "hero-widget",
                "per_page": 20,
                "page": 2,
            },
        )
        assert ("product_id", "123456") in query
        assert ("product_handle", "hero-widget") in query
        assert ("per_page", "20") in query
        assert ("page", "2") in query


# ── Fetch happy path ───────────────────────────────────────


class TestJudgeMeFetch:
    def test_fetch_happy_path(self, monkeypatch):
        from core.adapters.reviews.judgeme import JudgeMeAdapter
        _configure_judgeme(monkeypatch)
        a = JudgeMeAdapter()

        captured = {}

        def fake_get(url, headers=None):
            captured["url"] = url
            captured["headers"] = headers
            return _mock_judgeme_response([
                {
                    "id": 1001,
                    "rating": 5,
                    "title": "Love it",
                    "body": "Exceeded expectations.",
                    "reviewer": {"name": "Jane D."},
                    "verified": "buyer",
                    "created_at": "2025-01-04T12:34:56Z",
                    "product_external_id": "gid://shopify/Product/1",
                },
                {
                    "id": 1002,
                    "rating": 4,
                    "title": "Good",
                    "body": "Solid product.",
                    "reviewer": {"name": "John S."},
                    "verified": "unverified",
                    "created_at": "2025-01-05T09:00:00Z",
                    "product_external_id": "gid://shopify/Product/1",
                },
            ])

        with patch.object(a, "_http_get", side_effect=fake_get):
            result = a.execute(
                Capability.PRODUCT_REVIEWS_FETCH, dict(_VALID_FETCH),
            )

        assert result.ok
        assert result.data["count"] == 2
        assert result.data["page"] == 1
        assert result.data["per_page"] == 10
        assert len(result.data["reviews"]) == 2

        first = result.data["reviews"][0]
        assert first["id"] == "1001"
        assert first["rating"] == 5
        assert first["title"] == "Love it"
        assert first["body"] == "Exceeded expectations."
        assert first["reviewer_name"] == "Jane D."
        assert first["verified"] is True
        assert first["product_id"] == "gid://shopify/Product/1"

        second = result.data["reviews"][1]
        assert second["verified"] is False

        assert result.cost_usd == pytest.approx(0.0)
        assert captured["url"].startswith(
            "https://judge.me/api/v1/reviews?",
        )
        assert "api_token=judgeme_token_xxxxxxxx" in captured["url"]
        assert "shop_domain=demo.myshopify.com" in captured["url"]

    def test_fetch_rating_min_post_filters(self, monkeypatch):
        """Judge.me's public API ignores rating filters, so the
        adapter must post-filter to honour the normalised
        contract."""
        from core.adapters.reviews.judgeme import JudgeMeAdapter
        _configure_judgeme(monkeypatch)
        a = JudgeMeAdapter()

        def fake_get(url, headers=None):
            return _mock_judgeme_response([
                {"id": 1, "rating": 5, "body": "great"},
                {"id": 2, "rating": 3, "body": "mid"},
                {"id": 3, "rating": 1, "body": "bad"},
                {"id": 4, "rating": 4, "body": "good"},
            ])

        with patch.object(a, "_http_get", side_effect=fake_get):
            result = a.execute(
                Capability.PRODUCT_REVIEWS_FETCH,
                {"shop_domain": "x.myshopify.com", "rating_min": 4},
            )
        assert result.ok
        assert result.data["count"] == 2
        assert [r["id"] for r in result.data["reviews"]] == ["1", "4"]

    def test_fetch_verified_only_post_filters(self, monkeypatch):
        from core.adapters.reviews.judgeme import JudgeMeAdapter
        _configure_judgeme(monkeypatch)
        a = JudgeMeAdapter()

        def fake_get(url, headers=None):
            return _mock_judgeme_response([
                {"id": 1, "rating": 5, "verified": "buyer"},
                {"id": 2, "rating": 5, "verified": "unverified"},
                {"id": 3, "rating": 4, "verified": True},
            ])

        with patch.object(a, "_http_get", side_effect=fake_get):
            result = a.execute(
                Capability.PRODUCT_REVIEWS_FETCH,
                {
                    "shop_domain": "x.myshopify.com",
                    "verified_only": True,
                },
            )
        assert result.ok
        assert result.data["count"] == 2
        assert [r["id"] for r in result.data["reviews"]] == ["1", "3"]

    def test_fetch_non_dict_response_raises(self, monkeypatch):
        from core.adapters.errors import AdapterError
        from core.adapters.reviews.judgeme import JudgeMeAdapter
        _configure_judgeme(monkeypatch)
        a = JudgeMeAdapter()
        with patch.object(a, "_http_get", return_value="nope"):
            result = a.execute(
                Capability.PRODUCT_REVIEWS_FETCH, dict(_VALID_FETCH),
            )
        assert not result.ok
        assert isinstance(result.error, AdapterError)

    def test_fetch_missing_reviews_raises(self, monkeypatch):
        from core.adapters.errors import AdapterError
        from core.adapters.reviews.judgeme import JudgeMeAdapter
        _configure_judgeme(monkeypatch)
        a = JudgeMeAdapter()
        with patch.object(a, "_http_get", return_value={"foo": "bar"}):
            result = a.execute(
                Capability.PRODUCT_REVIEWS_FETCH, dict(_VALID_FETCH),
            )
        assert not result.ok
        assert isinstance(result.error, AdapterError)

    def test_fetch_auth_error_mapped(self, monkeypatch):
        from core.adapters.reviews.judgeme import JudgeMeAdapter
        _configure_judgeme(monkeypatch)
        a = JudgeMeAdapter()
        with patch.object(
            a, "_http_get",
            side_effect=AdapterAuthError(a.name, "bad token"),
        ):
            result = a.execute(
                Capability.PRODUCT_REVIEWS_FETCH, dict(_VALID_FETCH),
            )
        assert not result.ok
        assert isinstance(result.error, AdapterAuthError)

    def test_fetch_rate_limit_mapped(self, monkeypatch):
        from core.adapters.reviews.judgeme import JudgeMeAdapter
        _configure_judgeme(monkeypatch)
        a = JudgeMeAdapter()
        with patch.object(
            a, "_http_get",
            side_effect=AdapterRateLimited(a.name, "throttled"),
        ):
            result = a.execute(
                Capability.PRODUCT_REVIEWS_FETCH, dict(_VALID_FETCH),
            )
        assert not result.ok
        assert isinstance(result.error, AdapterRateLimited)


# ── Bootstrap ───────────────────────────────────────────────


class TestReviewsBootstrap:
    def test_register_all_adds_judgeme(self):
        from core.adapters.reviews.bootstrap import register_all
        status = register_all()
        assert "judgeme" in status

    def test_register_all_unconfigured_without_env(self):
        from core.adapters.reviews.bootstrap import register_all
        status = register_all()
        assert status["judgeme"] is False

    def test_register_all_configured_when_env_set(self, monkeypatch):
        from core.adapters.reviews.bootstrap import register_all
        _configure_judgeme(monkeypatch)
        status = register_all()
        assert status["judgeme"] is True

    def test_register_all_idempotent(self):
        from core.adapters.reviews.bootstrap import register_all
        register_all()
        register_all()
        assert len([
            n for n in get_registry().names() if n == "judgeme"
        ]) == 1


# ── Smart router routing + metrics capture ─────────────────


class TestReviewsRouterIntegration:
    def test_router_routes_product_reviews_fetch_to_judgeme(self, monkeypatch):
        from core.adapters.reviews.bootstrap import register_all
        _configure_judgeme(monkeypatch)
        register_all()
        chosen = get_router().route(Capability.PRODUCT_REVIEWS_FETCH)
        assert chosen.name == "judgeme"

    def test_router_raises_when_judgeme_unconfigured(self):
        from core.adapters.reviews.bootstrap import register_all
        register_all()
        with pytest.raises(NoAdapterAvailable):
            get_router().route(Capability.PRODUCT_REVIEWS_FETCH)

    def test_end_to_end_fetch_records_metrics(self, monkeypatch):
        """Wave 1 success criterion — the router reaches a brand-new
        external system AND MetricsCollector captures the outcome."""
        from core.adapters.reviews.bootstrap import register_all
        from core.adapters.reviews.judgeme import JudgeMeAdapter

        _configure_judgeme(monkeypatch)
        register_all()

        adapter = get_registry().get("judgeme")
        assert isinstance(adapter, JudgeMeAdapter)

        def fake_get(url, headers=None):
            return _mock_judgeme_response([
                {
                    "id": 42,
                    "rating": 5,
                    "title": "Five stars",
                    "body": "Great",
                    "reviewer": {"name": "Alice"},
                    "verified": "buyer",
                    "created_at": "2025-02-01T00:00:00Z",
                    "product_external_id": "gid://shopify/Product/7",
                },
            ])

        with patch.object(adapter, "_http_get", side_effect=fake_get):
            result = get_router().execute(
                Capability.PRODUCT_REVIEWS_FETCH, dict(_VALID_FETCH),
            )

        assert result.ok
        assert result.adapter == "judgeme"
        assert result.capability == "product_reviews_fetch"
        assert result.data["count"] == 1
        assert result.data["reviews"][0]["rating"] == 5

        stats = get_metrics().stats_for("judgeme")
        assert stats is not None
        assert stats["calls_total"] == 1
        assert stats["calls_success"] == 1
        assert stats["calls_failure"] == 0
        assert stats["success_rate"] == 1.0

    def test_router_records_failure_metric(self, monkeypatch):
        from core.adapters.reviews.bootstrap import register_all
        from core.adapters.reviews.judgeme import JudgeMeAdapter

        _configure_judgeme(monkeypatch)
        register_all()
        adapter = get_registry().get("judgeme")
        assert isinstance(adapter, JudgeMeAdapter)

        with patch.object(
            adapter, "_http_get",
            side_effect=AdapterAuthError(adapter.name, "bad token"),
        ):
            result = get_router().execute(
                Capability.PRODUCT_REVIEWS_FETCH, dict(_VALID_FETCH),
            )

        assert not result.ok
        stats = get_metrics().stats_for("judgeme")
        assert stats is not None
        assert stats["calls_total"] == 1
        assert stats["calls_failure"] == 1
        assert stats["calls_success"] == 0
