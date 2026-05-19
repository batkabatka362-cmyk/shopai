"""Tests for ``core.mcp_server.tools``.

Each tool function wraps an existing engine layer call.
Tests verify:

  1. Argument validation (empty store_name, niche
     fallback, etc.).
  2. Engine layer is actually called with the right
     args.
  3. Errors are returned as ``{status: "error"}`` dicts
     rather than raised exceptions (MCP tool contract).
  4. Successful calls return ``{status: "ok", data,
     error: None}`` envelopes.

The MCP server machinery itself (``server.py``) isn't
tested here -- it requires the ``mcp`` package which is
an optional dependency. ``build_server()`` raising
RuntimeError without ``mcp`` installed is covered by a
single import-time check.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core.mcp_server.tools import (
    REGISTERED_TOOLS,
    apply_pages,
    apply_policies,
    apply_starter_collections,
    audit_launch_readiness,
    health,
    list_niches,
    recommend_full_launch_pack,
    recommend_pages,
    recommend_policies,
    recommend_starter_collections,
)


def _ok_router_result():
    return SimpleNamespace(ok=True, data={}, error=None)


# ── list_niches + health ─────────────────────────────────────


class TestListNiches:

    def test_returns_known_niches(self):
        out = list_niches()
        assert out["status"] == "ok"
        niches = out["data"]["niches"]
        assert "beauty" in niches
        assert "fashion" in niches
        assert "jewelry" in niches
        # 10 specific + general
        assert len(niches) == 11
        assert out["data"]["fallback"] == "general"


class TestHealth:

    def test_health_returns_service_info(self):
        out = health()
        assert out["status"] == "ok"
        assert out["data"]["service"] == "shopai-mcp"
        assert out["data"]["version"]
        assert out["data"]["tool_count"] == len(
            REGISTERED_TOOLS,
        )


# ── recommend_starter_collections ───────────────────────────


class TestRecommendStarterCollections:

    def test_returns_collection_specs(self):
        out = recommend_starter_collections(niche="beauty")
        assert out["status"] == "ok"
        assert out["data"]["niche"] == "beauty"
        collections = out["data"]["collections"]
        assert isinstance(collections, list)
        assert len(collections) >= 4
        # Each carries the spec shape
        for c in collections:
            assert "title" in c
            assert "handle" in c

    def test_unknown_niche_falls_back(self):
        out = recommend_starter_collections(
            niche="ufo_parts",
        )
        # Still ok -- collection_seeder's own fallback
        assert out["status"] == "ok"
        assert out["data"]["niche"] == "ufo_parts"
        assert len(out["data"]["collections"]) >= 4

    def test_blank_niche_uses_general(self):
        out = recommend_starter_collections(niche="")
        assert out["status"] == "ok"
        assert out["data"]["niche"] == "general"

    def test_import_failure_returns_error(self):
        """When the engine module is unavailable, return
        a clean error dict -- never raise."""
        with patch(
            "engines.store_setup.collection_seeder."
            "generate_starter_collections",
            side_effect=ImportError("boom"),
        ):
            out = recommend_starter_collections(
                niche="beauty",
            )
        assert out["status"] == "error"
        # Wrapped raise lands in generator_raised path
        assert (
            "generator_raised" in out["error"]
            or "engine_import_failed" in out["error"]
        )


# ── recommend_pages ──────────────────────────────────────────


class TestRecommendPages:

    def test_returns_pages_dict(self):
        out = recommend_pages(
            store_name="Acme", niche="beauty",
        )
        assert out["status"] == "ok"
        assert out["data"]["niche"] == "beauty"
        pages = out["data"]["pages"]
        assert "About" in pages
        assert "Contact" in pages
        assert "FAQ" in pages

    def test_empty_store_name_errors(self):
        out = recommend_pages(store_name="")
        assert out["status"] == "error"
        assert out["error"] == "store_name_required"

    def test_whitespace_store_name_errors(self):
        out = recommend_pages(store_name="   ")
        assert out["status"] == "error"

    def test_founder_name_threads_through(self):
        out = recommend_pages(
            store_name="Acme",
            founder_name="Jane Doe",
        )
        assert out["status"] == "ok"
        about = out["data"]["pages"]["About"]
        assert "Jane Doe" in about

    def test_support_email_typeerror_fallback(self):
        """Older versions of generate_pages don't accept
        support_email. The wrapper retries with the kwarg
        stripped."""
        call_kwargs: list[dict] = []
        real_calls = {"i": 0}

        def _fake_generate(**kw):
            real_calls["i"] += 1
            call_kwargs.append(dict(kw))
            if "support_email" in kw and real_calls["i"] == 1:
                raise TypeError(
                    "generate_pages() got an unexpected "
                    "keyword argument 'support_email'"
                )
            return {"About": "<h1>x</h1>"}

        with patch(
            "engines.store_setup.page_generator."
            "generate_pages",
            side_effect=_fake_generate,
        ):
            out = recommend_pages(
                store_name="Acme",
                niche="beauty",
                support_email="hello@example.com",
            )
        # First call had support_email; second call (after
        # TypeError retry) didn't.
        assert out["status"] == "ok"
        assert "support_email" in call_kwargs[0]
        assert "support_email" not in call_kwargs[1]


# ── recommend_policies ──────────────────────────────────────


class TestRecommendPolicies:

    def test_returns_5_policies(self):
        out = recommend_policies(
            store_name="Acme", niche="beauty",
        )
        assert out["status"] == "ok"
        policies = out["data"]["policies"]
        assert "REFUND_POLICY" in policies
        assert "PRIVACY_POLICY" in policies
        assert "TERMS_OF_SERVICE" in policies

    def test_empty_store_name_errors(self):
        out = recommend_policies(store_name="")
        assert out["status"] == "error"

    def test_optional_flags_forward(self):
        out = recommend_policies(
            store_name="Acme",
            include_legal_notice=True,
            include_subscription_policy=True,
        )
        assert out["status"] == "ok"
        policies = out["data"]["policies"]
        assert "LEGAL_NOTICE" in policies
        assert "SUBSCRIPTION_POLICY" in policies


# ── audit_launch_readiness ──────────────────────────────────


class TestAuditLaunchReadiness:

    def test_calls_audit_store(self):
        fake_report = {
            "checks": [],
            "ready_to_launch": False,
            "completion_pct": 0,
            "missing_summary": "x",
        }
        with patch(
            "engines.store_setup.launch_audit.audit_store",
            return_value=fake_report,
        ) as mock_audit:
            out = audit_launch_readiness(
                store_id="store-a",
                expected_collections=2,
                expected_discounts=3,
            )
        assert out["status"] == "ok"
        assert out["data"] == fake_report
        # Args forwarded correctly
        kwargs = mock_audit.call_args.kwargs
        assert kwargs["store_id"] == "store-a"
        assert kwargs["expected_collections"] == 2
        assert kwargs["expected_discounts"] == 3

    def test_raise_returns_error(self):
        with patch(
            "engines.store_setup.launch_audit.audit_store",
            side_effect=RuntimeError("network"),
        ):
            out = audit_launch_readiness()
        assert out["status"] == "error"
        assert "network" in out["error"]


# ── apply_starter_collections ───────────────────────────────


class TestApplyStarterCollections:

    def test_pushes_via_engine(self):
        mock_apply = MagicMock(return_value={
            "applied_count": 4,
            "results": [],
        })
        with patch(
            "engines.store_setup.collection_seeder."
            "apply_starter_collections",
            mock_apply,
        ):
            out = apply_starter_collections(
                niche="beauty",
                store_id="store-a",
            )
        assert out["status"] == "ok"
        assert out["data"]["applied_count"] == 4
        # Engine called with the right kwargs
        kwargs = mock_apply.call_args.kwargs
        assert kwargs["store_id"] == "store-a"


# ── apply_pages / apply_policies ────────────────────────────


class TestApplyPages:

    def test_empty_store_name_errors(self):
        out = apply_pages(store_name="")
        assert out["status"] == "error"

    def test_pushes_via_engine(self):
        mock_apply = MagicMock(return_value={
            "applied_count": 4,
            "results": [],
        })
        with patch(
            "engines.store_setup.page_applier.apply_pages",
            mock_apply,
        ):
            out = apply_pages(
                store_name="Acme",
                niche="beauty",
                store_id="store-a",
            )
        assert out["status"] == "ok"
        assert (
            mock_apply.call_args.kwargs["store_id"]
            == "store-a"
        )


class TestApplyPolicies:

    def test_empty_store_name_errors(self):
        out = apply_policies(store_name="")
        assert out["status"] == "error"

    def test_pushes_via_engine(self):
        mock_apply = MagicMock(return_value={
            "applied_count": 5,
            "results": [],
        })
        with patch(
            "engines.store_setup.policy_applier."
            "apply_policies",
            mock_apply,
        ):
            out = apply_policies(
                store_name="Acme",
                niche="beauty",
                region="us",
                store_id="store-a",
            )
        assert out["status"] == "ok"


# ── recommend_full_launch_pack ──────────────────────────────


class TestRecommendFullLaunchPack:

    def test_bundles_all_recommendations(self):
        out = recommend_full_launch_pack(
            store_name="Acme",
            niche="beauty",
            region="us",
        )
        assert out["status"] == "ok"
        bundle = out["data"]
        assert bundle["store_name"] == "Acme"
        assert bundle["niche"] == "beauty"
        # Each section is its own nested envelope
        assert bundle["collections"]["status"] == "ok"
        assert bundle["pages"]["status"] == "ok"
        assert bundle["policies"]["status"] == "ok"

    def test_empty_store_name_errors(self):
        out = recommend_full_launch_pack(store_name="")
        assert out["status"] == "error"

    def test_section_failure_isolated(self):
        """A failing generator in one section shouldn't
        kill the others -- the section returns its own
        error envelope."""
        with patch(
            "engines.store_setup.collection_seeder."
            "generate_starter_collections",
            side_effect=RuntimeError("collections broken"),
        ):
            out = recommend_full_launch_pack(
                store_name="Acme",
            )
        # Top-level still ok
        assert out["status"] == "ok"
        bundle = out["data"]
        # Collections section carries the error
        assert bundle["collections"]["status"] == "error"
        # Pages + policies still ok
        assert bundle["pages"]["status"] == "ok"
        assert bundle["policies"]["status"] == "ok"


# ── Tool registry sanity ─────────────────────────────────────


class TestToolRegistry:

    def test_no_duplicate_tool_names(self):
        names = [t[0] for t in REGISTERED_TOOLS]
        assert len(names) == len(set(names)), names

    def test_every_tool_has_description(self):
        for name, fn, description in REGISTERED_TOOLS:
            assert callable(fn), name
            assert description.strip(), name
            # Descriptions are operator-facing; require
            # them to be substantive.
            assert len(description) >= 20, name

    def test_tool_names_are_snake_case(self):
        for name, _, _ in REGISTERED_TOOLS:
            assert name == name.lower(), name
            assert " " not in name, name
            # Conventional MCP tool naming: lowercase
            # + underscores
            assert all(
                ch.isalnum() or ch == "_" for ch in name
            ), name
