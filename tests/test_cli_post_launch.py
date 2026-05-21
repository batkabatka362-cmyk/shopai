"""Tests for ``shopai post-launch``.

Companion command to ``shopai launch``: runs SEO +
description enrichment over the store's products in one shot.
Default preview; ``--apply`` opts in to writes.

Coverage:
  - No products -> friendly empty message + exit 0
  - Preview without --apply -> no writes, both enrichers run
  - --apply happy path -> both writes succeed, exit 0
  - --apply partial failure -> exit 1 with breakdown
  - Router fetch failure -> friendly exit 0
  - JSON output (preview + apply)
  - Args propagate to underlying enrichers
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from io import StringIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


def _load_cli():
    spec = importlib.util.spec_from_file_location("shopai_cli", "cli.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def cli():
    return _load_cli()


def _capture(fn, *args, **kwargs):
    buf = StringIO()
    code = 0
    try:
        with patch("sys.stdout", buf):
            fn(*args, **kwargs)
    except SystemExit as e:
        code = int(e.code) if e.code is not None else 0
    return buf.getvalue(), code


def _ns(**kw):
    defaults = dict(
        store=None,
        niche="general",
        store_name="",
        limit=100,
        min_description_length=80,
        overwrite_seo=False,
        apply=False,
        audit=False,
        json=False,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _fake_sm():
    sm = MagicMock()
    sm.active_store_id = None
    return sm


def _ok_router(products):
    router = MagicMock()
    router.execute.return_value = SimpleNamespace(
        ok=True,
        data={"products": products},
        error=None,
    )
    return router


_SAMPLE = [
    {"id": "gid://shopify/Product/1", "title": "Lantern",
     "product_type": "Lighting", "vendor": "Acme",
     "body_html": ""},
    {"id": "gid://shopify/Product/2", "title": "Tent",
     "product_type": "Shelter", "vendor": "Acme",
     "body_html": ""},
]


class TestEmptyStore:

    def test_no_products_friendly_message(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "core.adapters.get_router",
            return_value=_ok_router([]),
        ):
            out, code = _capture(
                cli._cmd_post_launch, _ns(),
            )
        assert code == 0
        assert "no products to enrich" in out.lower()

    def test_no_products_json(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "core.adapters.get_router",
            return_value=_ok_router([]),
        ):
            out, code = _capture(
                cli._cmd_post_launch, _ns(json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert data["products_total"] == 0


class TestPreview:

    def test_preview_no_writes(self, cli):
        """Default mode: both enrichers compute candidates but
        ``apply_seo`` / ``apply_descriptions`` are never called."""
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "core.adapters.get_router",
            return_value=_ok_router(_SAMPLE),
        ), patch(
            "engines.store_setup.seo_meta_enricher.apply_seo",
        ) as seo_apply, patch(
            "engines.store_setup.product_description_enricher."
            "apply_descriptions",
        ) as desc_apply:
            out, code = _capture(
                cli._cmd_post_launch, _ns(),
            )
        seo_apply.assert_not_called()
        desc_apply.assert_not_called()
        assert code == 0
        assert "PREVIEW" in out
        assert "Re-run with --apply" in out

    def test_preview_json_carries_both_counts(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "core.adapters.get_router",
            return_value=_ok_router(_SAMPLE),
        ):
            out, code = _capture(
                cli._cmd_post_launch, _ns(json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert data["applied"] is False
        assert data["products_total"] == 2
        assert "seo" in data
        assert "descriptions" in data


class TestApplyHappyPath:

    def test_apply_clean_exits_0(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "core.adapters.get_router",
            return_value=_ok_router(_SAMPLE),
        ), patch(
            "engines.store_setup.seo_meta_enricher.apply_seo",
            return_value={
                "applied_count": 2,
                "results": [
                    {"product_id": "gid://shopify/Product/1",
                     "ok": True, "error": None},
                    {"product_id": "gid://shopify/Product/2",
                     "ok": True, "error": None},
                ],
            },
        ) as seo_apply, patch(
            "engines.store_setup.product_description_enricher."
            "apply_descriptions",
            return_value={
                "applied_count": 2,
                "results": [
                    {"product_id": "gid://shopify/Product/1",
                     "ok": True, "error": None},
                    {"product_id": "gid://shopify/Product/2",
                     "ok": True, "error": None},
                ],
            },
        ) as desc_apply:
            out, code = _capture(
                cli._cmd_post_launch, _ns(apply=True),
            )
        seo_apply.assert_called_once()
        desc_apply.assert_called_once()
        assert code == 0
        assert "APPLIED" in out
        assert "2 SEO updates" in out
        assert "2 description updates" in out


class TestApplyPartialFailure:

    def test_partial_failure_exits_1(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "core.adapters.get_router",
            return_value=_ok_router(_SAMPLE),
        ), patch(
            "engines.store_setup.seo_meta_enricher.apply_seo",
            return_value={
                "applied_count": 1,
                "results": [
                    {"product_id": "gid://shopify/Product/1",
                     "ok": True, "error": None},
                    {"product_id": "gid://shopify/Product/2",
                     "ok": False, "error": "rate_limited"},
                ],
            },
        ), patch(
            "engines.store_setup.product_description_enricher."
            "apply_descriptions",
            return_value={
                "applied_count": 2,
                "results": [
                    {"product_id": "gid://shopify/Product/1",
                     "ok": True, "error": None},
                    {"product_id": "gid://shopify/Product/2",
                     "ok": True, "error": None},
                ],
            },
        ):
            out, code = _capture(
                cli._cmd_post_launch, _ns(apply=True),
            )
        assert code == 1
        assert "PARTIAL" in out
        assert "SEO failures (1)" in out
        assert "rate_limited" in out


class TestResilience:

    def test_router_fetch_unavailable(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "core.adapters.get_router",
            side_effect=RuntimeError("network"),
        ):
            out, code = _capture(
                cli._cmd_post_launch, _ns(),
            )
        # Probe failure isn't a launch failure -- exit 0
        assert code == 0
        assert "unavailable" in out.lower()


class TestAuditFollowUp:
    """post-launch --audit chains the launch-audit after the
    apply phase so a single command does enrichment + readiness
    verification."""

    def test_default_off_no_audit_call(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "core.adapters.get_router",
            return_value=_ok_router(_SAMPLE),
        ), patch(
            "engines.store_setup.seo_meta_enricher.apply_seo",
            return_value={"applied_count": 2, "results": []},
        ), patch(
            "engines.store_setup.product_description_enricher."
            "apply_descriptions",
            return_value={"applied_count": 2, "results": []},
        ), patch(
            "engines.store_setup.launch_audit.audit_store",
        ) as audit_mock:
            out, code = _capture(
                cli._cmd_post_launch, _ns(apply=True),
            )
        assert code == 0
        # Default --audit unset -> audit_store never called
        audit_mock.assert_not_called()
        assert "Launch-audit follow-up" not in out

    def test_audit_flag_runs_after_apply(self, cli):
        audit_result = {
            "checks": [
                {"key": "legal_policies", "ok": True,
                 "applied": 5, "expected": 5, "missing": [],
                 "fix_hint": ""},
                {"key": "active_products", "ok": False,
                 "applied": 0, "expected": 1,
                 "missing": ["need 1"],
                 "fix_hint": "Run: shopai launch "
                             "--seed-products"},
            ],
            "ready_to_launch": False,
            "completion_pct": 50,
            "missing_summary": "active_products",
            "next_action": (
                "shopai launch --store-name <NAME> "
                "--niche <NICHE> --seed-products"
            ),
        }
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "core.adapters.get_router",
            return_value=_ok_router(_SAMPLE),
        ), patch(
            "engines.store_setup.seo_meta_enricher.apply_seo",
            return_value={"applied_count": 2, "results": []},
        ), patch(
            "engines.store_setup.product_description_enricher."
            "apply_descriptions",
            return_value={"applied_count": 2, "results": []},
        ), patch(
            "engines.store_setup.launch_audit.audit_store",
            return_value=audit_result,
        ) as audit_mock:
            out, code = _capture(
                cli._cmd_post_launch,
                _ns(apply=True, audit=True),
            )
        assert code == 0
        audit_mock.assert_called_once()
        assert "post-launch APPLIED" in out
        # Audit section + Next-action surfaced
        assert "Launch-audit follow-up" in out
        assert "[MISS] active_products" in out
        assert "fix: Run: shopai launch --seed-products" in out
        assert "Next: shopai launch" in out

    def test_audit_in_json(self, cli):
        audit_result = {
            "checks": [],
            "ready_to_launch": True,
            "completion_pct": 100,
            "missing_summary": "",
            "next_action": "",
        }
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "core.adapters.get_router",
            return_value=_ok_router(_SAMPLE),
        ), patch(
            "engines.store_setup.seo_meta_enricher.apply_seo",
            return_value={"applied_count": 2, "results": []},
        ), patch(
            "engines.store_setup.product_description_enricher."
            "apply_descriptions",
            return_value={"applied_count": 2, "results": []},
        ), patch(
            "engines.store_setup.launch_audit.audit_store",
            return_value=audit_result,
        ):
            out, code = _capture(
                cli._cmd_post_launch,
                _ns(apply=True, audit=True, json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert "audit_after_post_launch" in data
        assert data["audit_after_post_launch"]["ready_to_launch"] is True

    def test_audit_skipped_on_preview(self, cli):
        """--audit is intentionally a post-apply check.
        Running on preview (no --apply) doesn't fire the
        audit since no writes happened."""
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "core.adapters.get_router",
            return_value=_ok_router(_SAMPLE),
        ), patch(
            "engines.store_setup.launch_audit.audit_store",
        ) as audit_mock:
            out, code = _capture(
                cli._cmd_post_launch, _ns(audit=True),
            )
        # Preview path returns before the audit follow-up
        audit_mock.assert_not_called()

    def test_audit_raise_doesnt_break_apply(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "core.adapters.get_router",
            return_value=_ok_router(_SAMPLE),
        ), patch(
            "engines.store_setup.seo_meta_enricher.apply_seo",
            return_value={"applied_count": 2, "results": []},
        ), patch(
            "engines.store_setup.product_description_enricher."
            "apply_descriptions",
            return_value={"applied_count": 2, "results": []},
        ), patch(
            "engines.store_setup.launch_audit.audit_store",
            side_effect=RuntimeError("network"),
        ):
            out, code = _capture(
                cli._cmd_post_launch,
                _ns(apply=True, audit=True),
            )
        # Apply phase still succeeds; audit reports unavailable
        assert code == 0
        assert "post-launch APPLIED" in out
        assert "unavailable" in out.lower()


class TestKwargsPropagation:

    def test_niche_and_min_length_propagate(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "core.adapters.get_router",
            return_value=_ok_router(_SAMPLE),
        ), patch(
            "engines.store_setup.seo_meta_enricher.enrich_seo",
            return_value={"generated": [], "skipped": []},
        ) as seo_gen, patch(
            "engines.store_setup.product_description_enricher."
            "enrich_products",
            return_value={"generated": [], "skipped": []},
        ) as desc_gen:
            _capture(
                cli._cmd_post_launch,
                _ns(
                    niche="beauty",
                    store_name="Acme Beauty",
                    min_description_length=150,
                    overwrite_seo=True,
                ),
            )
        seo_kwargs = seo_gen.call_args.kwargs
        assert seo_kwargs["niche"] == "beauty"
        assert seo_kwargs["store_name"] == "Acme Beauty"
        assert seo_kwargs["overwrite_existing"] is True
        desc_kwargs = desc_gen.call_args.kwargs
        assert desc_kwargs["niche"] == "beauty"
        assert desc_kwargs["min_existing_length"] == 150
