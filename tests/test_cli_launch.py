"""Tests for ``shopai launch``.

Flagship CLI: single command store launch. Wraps
``launch_orchestrator.launch_store`` and renders the result.

Coverage:
  - Empty store_name -> friendly error + exit 1
  - All steps OK -> READY header, exit 0, post-launch
    next-step pointer
  - Partial fail -> NOT READY + failed-steps line
  - --strict + not ready -> exit 1
  - --strict + ready -> exit 0
  - --json output
  - Args propagate to launch_store
  - launch_store raises -> friendly text, exit 0
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from io import StringIO
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
        store_name="Acme",
        niche="general",
        region="us",
        founder_name=None,
        store_id=None,
        include_legal_notice=False,
        include_subscription_policy=False,
        logo_url=None,
        favicon_url=None,
        hero_url=None,
        og_image_url=None,
        seed_products=False,
        strict=False,
        audit=False,
        json=False,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _fake_sm():
    sm = MagicMock()
    sm.active_store_id = None
    return sm


def _ready_result():
    return {
        "policies": {"applied_count": 5, "results": []},
        "pages": {"applied_count": 4, "results": []},
        "checklist": [
            {"step": "policies", "ok": True, "applied": 5,
             "error": None},
            {"step": "pages", "ok": True, "applied": 4,
             "error": None},
        ],
        "ready_to_launch": True,
    }


def _partial_result():
    return {
        "policies": {"applied_count": 5, "results": []},
        "pages": {
            "applied_count": 0, "results": [],
            "error": "rejected",
        },
        "checklist": [
            {"step": "policies", "ok": True, "applied": 5,
             "error": None},
            {"step": "pages", "ok": False, "applied": 0,
             "error": "rejected"},
        ],
        "ready_to_launch": False,
    }


class TestEmptyName:

    def test_empty_name_exits_1(self, cli):
        result = {
            "policies": {"applied_count": 0, "results": []},
            "pages": {"applied_count": 0, "results": []},
            "checklist": [],
            "ready_to_launch": False,
            "error": "store_name_required",
        }
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "engines.store_setup.launch_orchestrator.launch_store",
            return_value=result,
        ):
            out, code = _capture(
                cli._cmd_launch, _ns(store_name=""),
            )
        assert code == 1
        assert "store_name is required" in out


class TestReady:

    def test_ready_header_exit_0(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "engines.store_setup.launch_orchestrator.launch_store",
            return_value=_ready_result(),
        ):
            out, code = _capture(cli._cmd_launch, _ns())
        assert code == 0
        assert "READY TO LAUNCH" in out
        assert "[OK  ] policies" in out
        assert "[OK  ] pages" in out
        # Mentions the next-step command
        assert "post-launch" in out

    def test_json_output(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "engines.store_setup.launch_orchestrator.launch_store",
            return_value=_ready_result(),
        ):
            out, code = _capture(
                cli._cmd_launch, _ns(json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert data["ready_to_launch"] is True


class TestPartial:

    def test_partial_shows_failed_steps(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "engines.store_setup.launch_orchestrator.launch_store",
            return_value=_partial_result(),
        ):
            out, code = _capture(cli._cmd_launch, _ns())
        # Default: informational exit 0
        assert code == 0
        assert "NOT READY" in out
        assert "[FAIL] pages" in out
        assert "error=rejected" in out
        assert "Failed steps" in out
        assert "launch-audit" in out

    def test_strict_partial_exits_1(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "engines.store_setup.launch_orchestrator.launch_store",
            return_value=_partial_result(),
        ):
            out, code = _capture(
                cli._cmd_launch, _ns(strict=True),
            )
        assert code == 1

    def test_strict_ready_exits_0(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "engines.store_setup.launch_orchestrator.launch_store",
            return_value=_ready_result(),
        ):
            out, code = _capture(
                cli._cmd_launch, _ns(strict=True),
            )
        assert code == 0


class TestResilience:

    def test_launch_store_raise(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "engines.store_setup.launch_orchestrator.launch_store",
            side_effect=RuntimeError("boom"),
        ):
            out, code = _capture(cli._cmd_launch, _ns())
        # Engine raise stays an exit-0 in default mode (the
        # mission is "tell the operator what happened", not
        # "blow up the cron")
        assert code == 0
        assert "failed" in out.lower()


class TestKwargPropagation:

    def test_all_kwargs_forwarded(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "engines.store_setup.launch_orchestrator.launch_store",
            return_value=_ready_result(),
        ) as launch_mock:
            _capture(
                cli._cmd_launch,
                _ns(
                    store_name="Acme Beauty",
                    niche="beauty",
                    region="eu",
                    founder_name="Jane",
                    store_id="store-a",
                    include_legal_notice=True,
                    include_subscription_policy=True,
                ),
            )
        kwargs = launch_mock.call_args.kwargs
        assert kwargs["store_name"] == "Acme Beauty"
        assert kwargs["niche"] == "beauty"
        assert kwargs["region"] == "eu"
        assert kwargs["founder_name"] == "Jane"
        assert kwargs["store_id"] == "store-a"
        assert kwargs["include_legal_notice"] is True
        assert kwargs["include_subscription_policy"] is True

    def test_skipped_steps_render_distinct_mark(self, cli):
        """A skipped step renders [SKIP] not [OK  ] so the
        operator can tell "didn't attempt" from "succeeded".
        """
        result = {
            "policies": {"applied_count": 5, "results": []},
            "pages": {"applied_count": 4, "results": []},
            "discount": {"applied": True, "code": "W"},
            "collections": {"applied_count": 4, "results": []},
            "brand": {"uploaded_count": 0, "files": [],
                      "skipped": True},
            "design": {"applied": False, "skipped": True,
                       "error": "no_main_theme"},
            "checklist": [
                {"step": "policies", "ok": True, "applied": 5,
                 "error": None},
                {"step": "pages", "ok": True, "applied": 4,
                 "error": None},
                {"step": "discount", "ok": True, "applied": 1,
                 "error": None},
                {"step": "collections", "ok": True, "applied": 4,
                 "error": None},
                {"step": "brand", "ok": True, "applied": 0,
                 "skipped": True, "error": None},
                {"step": "design", "ok": True, "applied": 0,
                 "skipped": True, "error": "no_main_theme"},
            ],
            "ready_to_launch": True,
        }
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "engines.store_setup.launch_orchestrator.launch_store",
            return_value=result,
        ):
            out, code = _capture(cli._cmd_launch, _ns())
        assert code == 0
        assert "[SKIP] brand" in out
        assert "[SKIP] design" in out
        # The skip reason renders as 'reason=' (not 'error=')
        assert "reason=no_main_theme" in out
        # Mandatory steps still render [OK  ]
        assert "[OK  ] policies" in out

    def test_audit_flag_runs_audit_after_launch(self, cli):
        audit_result = {
            "checks": [
                {"key": "legal_policies", "ok": True,
                 "applied": 5, "expected": 5, "missing": [],
                 "fix_hint": ""},
                {"key": "active_products", "ok": False,
                 "applied": 0, "expected": 1,
                 "missing": ["need 1 more"],
                 "fix_hint": "Add ACTIVE products via Shopify "
                             "admin"},
            ],
            "ready_to_launch": False,
            "completion_pct": 50,
            "missing_summary": "active_products: need 1 more",
        }
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "engines.store_setup.launch_orchestrator.launch_store",
            return_value=_ready_result(),
        ), patch(
            "engines.store_setup.launch_audit.audit_store",
            return_value=audit_result,
        ) as audit_mock:
            out, code = _capture(
                cli._cmd_launch, _ns(audit=True),
            )
        assert code == 0
        # Audit was called
        audit_mock.assert_called_once()
        # Launch READY header still rendered
        assert "READY TO LAUNCH" in out
        # Audit follow-up section + MISS line + fix
        assert "Launch-audit follow-up" in out
        assert "1/2 pass" in out
        assert "[MISS] active_products" in out
        assert "fix: Add ACTIVE products" in out

    def test_audit_follow_up_includes_next_action(self, cli):
        """When the audit follow-up surfaces gaps, the Next:
        line points the operator at the highest-leverage
        command."""
        audit_result = {
            "checks": [
                {"key": "legal_policies", "ok": False,
                 "applied": 0, "expected": 5,
                 "missing": ["REFUND_POLICY"],
                 "fix_hint": "Run: shopai launch ..."},
                {"key": "standard_pages", "ok": False,
                 "applied": 0, "expected": 4,
                 "missing": ["about"],
                 "fix_hint": "Run: shopai launch ..."},
                {"key": "active_discounts", "ok": True,
                 "applied": 1, "expected": 1, "missing": [],
                 "fix_hint": ""},
            ],
            "ready_to_launch": False,
            "completion_pct": 33,
            "missing_summary": "...",
        }
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "engines.store_setup.launch_orchestrator.launch_store",
            return_value=_ready_result(),
        ), patch(
            "engines.store_setup.launch_audit.audit_store",
            return_value=audit_result,
        ):
            out, code = _capture(
                cli._cmd_launch, _ns(audit=True),
            )
        # Next line surfaces under the follow-up section
        assert "Next: shopai launch" in out

    def test_audit_flag_skipped_by_default(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "engines.store_setup.launch_orchestrator.launch_store",
            return_value=_ready_result(),
        ), patch(
            "engines.store_setup.launch_audit.audit_store",
        ) as audit_mock:
            out, code = _capture(cli._cmd_launch, _ns())
        # Default --audit unset -> audit_store never called
        audit_mock.assert_not_called()
        assert "Launch-audit follow-up" not in out

    def test_audit_flag_in_json(self, cli):
        audit_result = {
            "checks": [],
            "ready_to_launch": True,
            "completion_pct": 100,
        }
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "engines.store_setup.launch_orchestrator.launch_store",
            return_value=_ready_result(),
        ), patch(
            "engines.store_setup.launch_audit.audit_store",
            return_value=audit_result,
        ):
            out, code = _capture(
                cli._cmd_launch, _ns(audit=True, json=True),
            )
        assert code == 0
        data = json.loads(out)
        # Both launch result + audit_after_launch in one payload
        assert data["ready_to_launch"] is True
        assert "audit_after_launch" in data
        assert data["audit_after_launch"]["ready_to_launch"] is True

    def test_audit_failure_surfaces_friendly(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "engines.store_setup.launch_orchestrator.launch_store",
            return_value=_ready_result(),
        ), patch(
            "engines.store_setup.launch_audit.audit_store",
            side_effect=RuntimeError("network"),
        ):
            out, code = _capture(
                cli._cmd_launch, _ns(audit=True),
            )
        # Audit raise doesn't break the launch CLI -- launch
        # result still surfaced, audit reported unavailable.
        assert code == 0
        assert "READY TO LAUNCH" in out
        assert "unavailable" in out.lower()

    def test_seed_products_flag_forwarded(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "engines.store_setup.launch_orchestrator.launch_store",
            return_value=_ready_result(),
        ) as launch_mock:
            _capture(
                cli._cmd_launch, _ns(seed_products=True),
            )
        kwargs = launch_mock.call_args.kwargs
        assert kwargs["seed_products"] is True

    def test_brand_urls_forwarded(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "engines.store_setup.launch_orchestrator.launch_store",
            return_value=_ready_result(),
        ) as launch_mock:
            _capture(
                cli._cmd_launch,
                _ns(
                    logo_url="https://cdn/logo.png",
                    favicon_url="https://cdn/favicon.ico",
                    hero_url="https://cdn/hero.jpg",
                    og_image_url="https://cdn/og.jpg",
                ),
            )
        kwargs = launch_mock.call_args.kwargs
        assert kwargs["logo_url"] == "https://cdn/logo.png"
        assert kwargs["favicon_url"] == "https://cdn/favicon.ico"
        assert kwargs["hero_url"] == "https://cdn/hero.jpg"
        assert kwargs["og_image_url"] == "https://cdn/og.jpg"
