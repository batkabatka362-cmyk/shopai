"""Tests for the Metabase analytics adapter.

Real HTTP calls are forbidden — every test patches
``_http_post`` to return canned responses.

Coverage:
  * Metadata (name, category, priority, narrow capability set)
  * is_configured() requires both METABASE_URL and METABASE_API_KEY
  * Auth: X-API-KEY header
  * Card-mode query: validation, happy path, csv format, params
  * Dataset-mode query: validation, happy path, template tags
  * Mode conflict (card_id + sql) rejected
  * Missing-mode rejected
  * TRACK_EVENT + IDENTIFY rejected (Metabase is read-only)
  * Response normalisation ({data: {rows, cols}})
  * Bootstrap registration
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


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for var in (
        "METABASE_URL",
        "METABASE_API_KEY",
        "POSTHOG_API_KEY",
        "MIXPANEL_TOKEN",
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


def _configure(
    monkeypatch,
    *,
    url="https://metabase.example.com",
    api_key="mb-test-key",
):
    monkeypatch.setenv("METABASE_URL", url)
    monkeypatch.setenv("METABASE_API_KEY", api_key)
    get_config().reload()


# Canned /api/dataset response shape.
_CANNED_DATASET_RESPONSE = {
    "data": {
        "rows": [
            [1, "Alice", 100.0],
            [2, "Bob", 75.0],
        ],
        "cols": [
            {"name": "id", "display_name": "ID"},
            {"name": "name", "display_name": "Name"},
            {"name": "revenue", "display_name": "Revenue"},
        ],
    },
}


# ── Metadata ──────────────────────────────────────────────────


class TestMetabaseMetadata:
    def test_metadata(self):
        from core.adapters.analytics.metabase import MetabaseAdapter
        a = MetabaseAdapter()
        assert a.name == "metabase"
        assert a.category == AdapterCategory.ANALYTICS
        # Narrow capability set: Metabase is read-only.
        assert Capability.ANALYTICS_QUERY in a.capabilities
        assert Capability.ANALYTICS_TRACK_EVENT not in a.capabilities
        assert Capability.ANALYTICS_IDENTIFY not in a.capabilities
        # Below PostHog (85) so track/identify calls don't drift
        # here even if capability ever widens.
        assert a.priority < 85


class TestMetabaseConfiguration:
    def test_unconfigured_without_url(self, monkeypatch):
        from core.adapters.analytics.metabase import MetabaseAdapter
        monkeypatch.setenv("METABASE_API_KEY", "mb-key")
        get_config().reload()
        assert not MetabaseAdapter().is_configured()

    def test_unconfigured_without_api_key(self, monkeypatch):
        from core.adapters.analytics.metabase import MetabaseAdapter
        monkeypatch.setenv("METABASE_URL", "https://mb.example.com")
        get_config().reload()
        assert not MetabaseAdapter().is_configured()

    def test_configured_with_both(self, monkeypatch):
        from core.adapters.analytics.metabase import MetabaseAdapter
        _configure(monkeypatch)
        assert MetabaseAdapter().is_configured()

    def test_base_url_trailing_slash_stripped(self, monkeypatch):
        from core.adapters.analytics.metabase import MetabaseAdapter
        _configure(monkeypatch, url="https://mb.example.com/")
        a = MetabaseAdapter()
        assert a._get_base_url() == "https://mb.example.com"


# ── Auth ─────────────────────────────────────────────────────


class TestMetabaseAuth:
    def test_x_api_key_header(self, monkeypatch):
        from core.adapters.analytics.metabase import MetabaseAdapter
        _configure(monkeypatch, api_key="mb-secret-xyz")
        a = MetabaseAdapter()
        headers = a._auth_headers()
        assert headers["X-API-KEY"] == "mb-secret-xyz"
        # No Authorization header — Metabase rejects Bearer.
        assert "Authorization" not in headers


# ── Mode validation ──────────────────────────────────────────


class TestMetabaseModeValidation:
    def test_no_mode_rejected(self, monkeypatch):
        from core.adapters.analytics.metabase import MetabaseAdapter
        _configure(monkeypatch)
        a = MetabaseAdapter()
        result = a.execute(Capability.ANALYTICS_QUERY, {})
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_both_modes_rejected(self, monkeypatch):
        from core.adapters.analytics.metabase import MetabaseAdapter
        _configure(monkeypatch)
        a = MetabaseAdapter()
        result = a.execute(
            Capability.ANALYTICS_QUERY,
            {"card_id": 1, "sql": "SELECT 1", "database_id": 1},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)
        assert "both" in str(result.error).lower()

    def test_sql_requires_database_id(self, monkeypatch):
        from core.adapters.analytics.metabase import MetabaseAdapter
        _configure(monkeypatch)
        a = MetabaseAdapter()
        result = a.execute(
            Capability.ANALYTICS_QUERY, {"sql": "SELECT 1"},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)


# ── Card-mode query ──────────────────────────────────────────


class TestMetabaseCardMode:
    def test_card_query_happy_path(self, monkeypatch):
        from core.adapters.analytics.metabase import MetabaseAdapter
        _configure(monkeypatch)
        a = MetabaseAdapter()

        with patch.object(
            a, "_http_post", return_value=_CANNED_DATASET_RESPONSE,
        ) as mock_post:
            result = a.execute(
                Capability.ANALYTICS_QUERY, {"card_id": 42},
            )

        assert result.ok
        assert result.data["card_id"] == 42
        assert result.data["format"] == "json"
        assert result.data["count"] == 2
        assert result.data["columns"] == ["id", "name", "revenue"]
        assert result.data["rows"][0] == [1, "Alice", 100.0]

        called_url = mock_post.call_args.args[0]
        assert "/api/card/42/query/json" in called_url

    def test_card_query_with_parameters(self, monkeypatch):
        from core.adapters.analytics.metabase import MetabaseAdapter
        _configure(monkeypatch)
        a = MetabaseAdapter()

        params_list = [
            {"type": "date/single", "target": ["variable", "from_date"],
             "value": "2026-01-01"},
        ]
        with patch.object(
            a, "_http_post", return_value=_CANNED_DATASET_RESPONSE,
        ) as mock_post:
            a.execute(
                Capability.ANALYTICS_QUERY,
                {"card_id": 7, "parameters": params_list},
            )

        sent_body = mock_post.call_args.args[1]
        assert sent_body["parameters"] == params_list

    def test_card_query_csv_format(self, monkeypatch):
        from core.adapters.analytics.metabase import MetabaseAdapter
        _configure(monkeypatch)
        a = MetabaseAdapter()

        with patch.object(
            a, "_http_post",
            return_value="id,name\n1,Alice\n2,Bob",
        ) as mock_post:
            result = a.execute(
                Capability.ANALYTICS_QUERY,
                {"card_id": 42, "format": "csv"},
            )

        assert result.ok
        assert result.data["format"] == "csv"
        called_url = mock_post.call_args.args[0]
        assert "/api/card/42/query/csv" in called_url
        # CSV text is surfaced as a single row so the caller
        # can stream-parse it without this adapter inventing a
        # dialect.
        assert result.data["columns"] == ["csv"]

    def test_card_id_must_be_int(self, monkeypatch):
        from core.adapters.analytics.metabase import MetabaseAdapter
        _configure(monkeypatch)
        a = MetabaseAdapter()
        result = a.execute(
            Capability.ANALYTICS_QUERY, {"card_id": "not-int"},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_invalid_format_rejected(self, monkeypatch):
        from core.adapters.analytics.metabase import MetabaseAdapter
        _configure(monkeypatch)
        a = MetabaseAdapter()
        result = a.execute(
            Capability.ANALYTICS_QUERY,
            {"card_id": 1, "format": "xml"},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)


# ── Dataset-mode query ───────────────────────────────────────


class TestMetabaseDatasetMode:
    def test_dataset_query_happy_path(self, monkeypatch):
        from core.adapters.analytics.metabase import MetabaseAdapter
        _configure(monkeypatch)
        a = MetabaseAdapter()

        with patch.object(
            a, "_http_post", return_value=_CANNED_DATASET_RESPONSE,
        ) as mock_post:
            result = a.execute(
                Capability.ANALYTICS_QUERY,
                {
                    "database_id": 3,
                    "sql": "SELECT id, name, SUM(amount) FROM orders",
                },
            )

        assert result.ok
        assert result.data["database_id"] == 3
        assert result.data["count"] == 2

        called_url = mock_post.call_args.args[0]
        assert called_url.endswith("/api/dataset")

        sent_body = mock_post.call_args.args[1]
        assert sent_body["type"] == "native"
        assert sent_body["database"] == 3
        assert sent_body["native"]["query"].startswith("SELECT id")

    def test_dataset_with_template_tags(self, monkeypatch):
        from core.adapters.analytics.metabase import MetabaseAdapter
        _configure(monkeypatch)
        a = MetabaseAdapter()

        tags = {
            "from_date": {
                "type": "date",
                "name": "from_date",
                "display-name": "From Date",
            },
        }
        with patch.object(
            a, "_http_post", return_value=_CANNED_DATASET_RESPONSE,
        ) as mock_post:
            a.execute(
                Capability.ANALYTICS_QUERY,
                {
                    "database_id": 1,
                    "sql": "SELECT 1 WHERE d > {{from_date}}",
                    "template_tags": tags,
                },
            )
        sent_body = mock_post.call_args.args[1]
        assert sent_body["native"]["template-tags"] == tags

    def test_database_id_must_be_int(self, monkeypatch):
        from core.adapters.analytics.metabase import MetabaseAdapter
        _configure(monkeypatch)
        a = MetabaseAdapter()
        result = a.execute(
            Capability.ANALYTICS_QUERY,
            {"database_id": "abc", "sql": "SELECT 1"},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)


# ── Read-only enforcement ────────────────────────────────────


class TestMetabaseReadOnly:
    def test_track_event_rejected(self, monkeypatch):
        """Metabase doesn't capture events — the capability is
        narrowed at the class level so the router never dispatches
        a track call here. But if someone invokes the adapter
        directly with TRACK_EVENT, surface a clear validation
        error instead of a NotImplementedError traceback."""
        from core.adapters.analytics.metabase import MetabaseAdapter
        _configure(monkeypatch)
        a = MetabaseAdapter()
        # Execute the internal handler directly — bypasses the
        # enum filter that normally blocks non-advertised caps.
        # Should raise AdapterValidationError (not NotImplementedError)
        # so callers get a clear "wrong tool" message.
        with pytest.raises(AdapterValidationError):
            a._do_track(
                Capability.ANALYTICS_TRACK_EVENT, {"event": "foo"},
            )
        with pytest.raises(AdapterValidationError):
            a._do_identify(
                Capability.ANALYTICS_IDENTIFY, {"distinct_id": "u1"},
            )

    def test_track_event_capability_narrowed(self, monkeypatch):
        """Exercised through execute(): the base dispatch rejects
        TRACK_EVENT because the adapter's ``capabilities`` set
        omits it — the router would refuse to route it here."""
        from core.adapters.analytics.metabase import MetabaseAdapter
        _configure(monkeypatch)
        a = MetabaseAdapter()
        # BaseAdapter.execute checks capability ∈ capabilities.
        result = a.execute(
            Capability.ANALYTICS_TRACK_EVENT,
            {"event": "pageview", "distinct_id": "u1"},
        )
        assert not result.ok


# ── Response normalisation ───────────────────────────────────


class TestMetabaseResponseNormalisation:
    def test_non_dict_response_yields_empty(self, monkeypatch):
        from core.adapters.analytics.metabase import MetabaseAdapter
        _configure(monkeypatch)
        a = MetabaseAdapter()
        rows, cols = a._extract_rows_columns("not a dict", "json")
        assert rows == []
        assert cols == []

    def test_missing_data_block(self, monkeypatch):
        from core.adapters.analytics.metabase import MetabaseAdapter
        _configure(monkeypatch)
        a = MetabaseAdapter()
        rows, cols = a._extract_rows_columns({"status": "ok"}, "json")
        assert rows == []
        assert cols == []

    def test_display_name_fallback(self, monkeypatch):
        from core.adapters.analytics.metabase import MetabaseAdapter
        _configure(monkeypatch)
        a = MetabaseAdapter()
        raw = {
            "data": {
                "rows": [[1]],
                "cols": [{"display_name": "Count"}],
            },
        }
        rows, cols = a._extract_rows_columns(raw, "json")
        assert cols == ["Count"]


# ── CSV transport ────────────────────────────────────────────


class TestMetabaseCsvTransport:
    """Metabase's /query/csv endpoint returns text/csv. The
    analytics base's `_http_post` unconditionally calls `.json()`,
    so the adapter overrides `_http_post` to branch on URL
    suffix. Without this, real CSV calls would raise
    `invalid JSON` — tests don't catch that when they patch
    `_http_post` at the adapter level."""

    def test_csv_url_returns_raw_text(self, monkeypatch):
        from core.adapters.analytics import metabase as mb_mod
        from core.adapters.analytics.metabase import MetabaseAdapter
        _configure(monkeypatch)
        a = MetabaseAdapter()

        class _FakeResp:
            status_code = 200
            text = "id,name\n1,Alice\n"

        calls: dict = {}

        def _fake_post(url, **kwargs):
            calls["url"] = url
            calls["headers"] = kwargs.get("headers", {})
            return _FakeResp()

        monkeypatch.setattr(mb_mod._requests, "post", _fake_post)

        result = a._http_post(
            f"{a._get_base_url()}/api/card/1/query/csv", {},
        )
        assert result == "id,name\n1,Alice\n"
        assert calls["headers"].get("Accept") == "text/csv"

    def test_json_url_still_delegates_to_base(self, monkeypatch):
        from core.adapters.analytics import metabase as mb_mod
        from core.adapters.analytics.metabase import MetabaseAdapter
        _configure(monkeypatch)
        a = MetabaseAdapter()

        class _FakeResp:
            status_code = 200
            text = '{"data": {"rows": [[1]], "cols": []}}'

            def json(self):
                import json as _json
                return _json.loads(self.text)

        def _fake_post(url, **kwargs):
            return _FakeResp()

        monkeypatch.setattr(mb_mod._requests, "post", _fake_post)
        # analytics base also imports requests under its own alias
        from core.adapters.analytics import _base as ab_mod
        monkeypatch.setattr(ab_mod._requests, "post", _fake_post)

        result = a._http_post(
            f"{a._get_base_url()}/api/dataset", {},
        )
        assert isinstance(result, dict)
        assert result["data"]["rows"] == [[1]]


# ── Bootstrap ────────────────────────────────────────────────


class TestAnalyticsBootstrapIncludesMetabase:
    def test_register_all_adds_metabase(self):
        from core.adapters.analytics.bootstrap import register_all
        status = register_all()
        assert "metabase" in status
        assert "posthog" in status
        assert "mixpanel" in status

    def test_register_all_idempotent(self):
        from core.adapters.analytics.bootstrap import register_all
        register_all()
        register_all()
        count = len([
            n for n in get_registry().names() if n == "metabase"
        ])
        assert count == 1
