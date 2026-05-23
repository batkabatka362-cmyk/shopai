"""Tests for ``shopai store design`` -- read-only preview of
store_design engine recommendations.

The command runs the store_design engine and surfaces its
four output sections (layout / color / navigation / mobile).
Doesn't modify the live store -- this is the foundation for a
future Phase 7 writeback. Tests cover:

  - All four sections render in the default 'all' mode
  - --section narrows to a single block
  - --json emits a structured envelope per section
  - Engine failure surfaces cleanly (exit 1)
  - No-active-store fallback (engine runs with default profile)
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from io import StringIO
from unittest.mock import patch

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
    defaults = dict(store_id=None, json=False, section="all")
    defaults.update(kw)
    return argparse.Namespace(**defaults)


# ─── Default render ──────────────────────────────────────────


class TestDefaultRender:

    def test_renders_all_four_sections(self, cli):
        out, code = _capture(cli._cmd_store_design, _ns())
        assert code == 0
        # Header
        assert "Store Design Preview" in out
        # All four sections present
        assert "== Layout" in out
        assert "== Color palette" in out
        assert "== Navigation" in out
        assert "== Mobile" in out
        # Read-only footer points at design-apply
        assert "Read-only preview" in out
        assert "shopai store design-apply" in out

    def test_default_profile_when_no_store(self, cli):
        out, code = _capture(cli._cmd_store_design, _ns())
        assert code == 0
        # No-active-store hint surfaces
        assert "no active store" in out


# ─── --section filter ────────────────────────────────────────


class TestSectionFilter:

    @pytest.mark.parametrize("section,expected_header,others", [
        ("layout", "== Layout",
         ["== Color palette", "== Navigation", "== Mobile"]),
        ("color", "== Color palette",
         ["== Layout", "== Navigation", "== Mobile"]),
        ("navigation", "== Navigation",
         ["== Layout", "== Color palette", "== Mobile"]),
        ("mobile", "== Mobile",
         ["== Layout", "== Color palette", "== Navigation"]),
    ])
    def test_filter_shows_only_matching_section(
        self, cli, section, expected_header, others,
    ):
        out, _ = _capture(
            cli._cmd_store_design, _ns(section=section),
        )
        assert expected_header in out
        for other in others:
            assert other not in out


# ─── JSON envelope ───────────────────────────────────────────


class TestJsonEnvelope:

    def test_json_emits_all_section_keys_by_default(self, cli):
        out, _ = _capture(
            cli._cmd_store_design, _ns(json=True),
        )
        data = json.loads(out)
        for key in (
            "layout_recommendations",
            "color_palette",
            "navigation",
            "mobile_optimizations",
            "estimated_conversion_lift",
        ):
            assert key in data

    def test_json_section_filter_drops_others(self, cli):
        out, _ = _capture(
            cli._cmd_store_design, _ns(json=True, section="color"),
        )
        data = json.loads(out)
        assert "color_palette" in data
        assert "layout_recommendations" not in data
        assert "navigation" not in data

    def test_json_includes_conversion_lift(self, cli):
        out, _ = _capture(
            cli._cmd_store_design, _ns(json=True),
        )
        data = json.loads(out)
        # The engine returns a numeric lift (may be 0.0 but
        # the key MUST be present for downstream consumers)
        assert isinstance(data["estimated_conversion_lift"], (int, float))


# ─── Engine error handling ──────────────────────────────────


class TestErrorHandling:

    def test_engine_failure_exits_1(self, cli):
        from engines.store_design.flow import StoreDesignEngine

        def _boom(self, _input):
            return {
                "status": "error",
                "data": None,
                "meta": {"engine": "store_design", "timestamp": "t",
                         "elapsed_seconds": 0.0},
                "error": "synthetic failure",
            }

        with patch.object(StoreDesignEngine, "run", _boom):
            out, code = _capture(
                cli._cmd_store_design, _ns(),
            )
        assert code == 1
        assert "no recommendations" in out

    def test_engine_raise_exits_1(self, cli):
        from engines.store_design.flow import StoreDesignEngine
        with patch.object(
            StoreDesignEngine, "run",
            side_effect=RuntimeError("engine broken"),
        ):
            out, code = _capture(
                cli._cmd_store_design, _ns(),
            )
        assert code == 1
        assert "unavailable" in out.lower()

    def test_engine_error_json_envelope(self, cli):
        from engines.store_design.flow import StoreDesignEngine

        def _boom(self, _input):
            return {
                "status": "error",
                "data": None,
                "meta": {"engine": "store_design", "timestamp": "t",
                         "elapsed_seconds": 0.0},
                "error": "synthetic failure",
            }

        with patch.object(StoreDesignEngine, "run", _boom):
            out, code = _capture(
                cli._cmd_store_design, _ns(json=True),
            )
        assert code == 1
        data = json.loads(out)
        assert data["status"] == "error"
        assert "synthetic failure" in data["error"]


# ─── Output content ──────────────────────────────────────────


class TestOutputContent:

    def test_layout_shows_priority_and_impact(self, cli):
        out, _ = _capture(
            cli._cmd_store_design, _ns(section="layout"),
        )
        # The default engine emits at least one recommendation
        # with a priority bracket and "impact:" line
        assert "[" in out  # priority bracket
        assert "impact:" in out

    def test_color_palette_includes_cta(self, cli):
        out, _ = _capture(
            cli._cmd_store_design, _ns(section="color"),
        )
        # Default palette includes the cta color row
        assert "cta" in out

    def test_navigation_items_sorted_by_priority(self, cli):
        out, _ = _capture(
            cli._cmd_store_design, _ns(json=True, section="navigation"),
        )
        data = json.loads(out)
        items = data["navigation"]["menu_items"]
        # Operator-rendered text sorts by priority -- verify the
        # underlying data carries the priority field for sorting
        for item in items:
            assert "priority" in item

    def test_mobile_optimization_has_area_and_recommendation(
        self, cli,
    ):
        out, _ = _capture(
            cli._cmd_store_design, _ns(json=True, section="mobile"),
        )
        data = json.loads(out)
        opts = data["mobile_optimizations"]
        # At least one mobile optimization with both fields
        assert len(opts) > 0
        for m in opts:
            assert "area" in m
            assert "recommendation" in m


# ─── design-apply ────────────────────────────────────────────


def _apply_ns(**kw):
    defaults = dict(
        theme_id="gid://shopify/OnlineStoreTheme/1",
        store=None, json=False,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


class TestDesignApply:
    """`shopai store design-apply` runs the engine then writes
    the tokens + snippet to the named theme via the existing
    design_applier (Pattern Z compliant)."""

    def test_missing_theme_id_fails_fast(self, cli):
        out, code = _capture(
            cli._cmd_store_design_apply,
            _apply_ns(theme_id=""),
        )
        assert code == 1
        assert "--theme-id is required" in out

    def test_success_renders_applied_files(self, cli):
        from unittest.mock import MagicMock
        apply_result = {
            "applied": True,
            "theme_id": "gid://shopify/OnlineStoreTheme/1",
            "files_written": [
                "assets/shopai-design-tokens.json",
                "snippets/shopai-design-recommendations.liquid",
            ],
            "error": None,
        }
        with patch(
            "engines.store_design.design_applier.apply_design",
            return_value=apply_result,
        ):
            out, code = _capture(
                cli._cmd_store_design_apply, _apply_ns(),
            )
        assert code == 0
        assert "Applied store_design to theme" in out
        assert "shopai-design-tokens.json" in out
        # Drill-down hint to engine summary
        assert (
            "shopai engine summary store_design" in out
        )

    def test_failure_exits_1(self, cli):
        apply_result = {
            "applied": False,
            "theme_id": "gid://shopify/OnlineStoreTheme/1",
            "files_written": [],
            "error": "router_unavailable",
        }
        with patch(
            "engines.store_design.design_applier.apply_design",
            return_value=apply_result,
        ):
            out, code = _capture(
                cli._cmd_store_design_apply, _apply_ns(),
            )
        assert code == 1
        assert "Apply failed: router_unavailable" in out

    def test_json_envelope(self, cli):
        apply_result = {
            "applied": True,
            "theme_id": "gid://shopify/OnlineStoreTheme/1",
            "files_written": ["a.json", "b.liquid"],
            "error": None,
        }
        with patch(
            "engines.store_design.design_applier.apply_design",
            return_value=apply_result,
        ):
            out, code = _capture(
                cli._cmd_store_design_apply,
                _apply_ns(json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert data["status"] == "ok"
        assert data["result"]["applied"] is True

    def test_engine_failure_surfaces(self, cli):
        with patch(
            "engines.store_design.flow.StoreDesignEngine.run",
            side_effect=RuntimeError("engine boom"),
        ):
            out, code = _capture(
                cli._cmd_store_design_apply, _apply_ns(),
            )
        assert code == 1
        assert "engine boom" in out


# ─── brand-upload ─────────────────────────────────────────────


def _brand_ns(**kw):
    defaults = dict(
        store_name="Acme",
        logo_url="https://cdn.example.com/logo.png",
        favicon_url="https://cdn.example.com/fav.png",
        hero_url="",
        og_image_url="",
        store=None,
        json=False,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


class TestBrandUpload:
    """`shopai store brand-upload` pushes brand asset URLs
    through engines.store_setup.brand_uploader. Stand-alone
    surface mirroring launch_orchestrator's Step 5."""

    def test_missing_store_name_fails(self, cli):
        out, code = _capture(
            cli._cmd_store_brand_upload,
            _brand_ns(store_name=""),
        )
        assert code == 1
        assert "--store-name is required" in out

    def test_missing_logo_and_favicon_fails(self, cli):
        out, code = _capture(
            cli._cmd_store_brand_upload,
            _brand_ns(logo_url="", favicon_url=""),
        )
        assert code == 1
        assert "logo-url" in out
        assert "favicon-url" in out

    def test_success_renders_uploaded_files(self, cli):
        upload_result = {
            "uploaded_count": 2,
            "files": [
                {"asset": "logo", "file_id": "gid://1"},
                {"asset": "favicon", "file_id": "gid://2"},
            ],
            "missing_assets": ["hero", "og_image"],
            "ok": True,
        }
        with patch(
            "engines.store_setup.brand_uploader."
            "upload_brand_assets",
            return_value=upload_result,
        ):
            out, code = _capture(
                cli._cmd_store_brand_upload, _brand_ns(),
            )
        assert code == 0
        assert "Uploaded 2 brand asset(s)" in out
        assert "logo" in out
        assert "Missing (optional): hero, og_image" in out
        # Drill-down hint to launch-audit
        assert "shopai launch-audit" in out

    def test_failure_exits_1(self, cli):
        upload_result = {
            "uploaded_count": 0,
            "files": [],
            "missing_assets": ["logo", "favicon"],
            "ok": False,
            "error": "router_unavailable",
        }
        with patch(
            "engines.store_setup.brand_uploader."
            "upload_brand_assets",
            return_value=upload_result,
        ):
            out, code = _capture(
                cli._cmd_store_brand_upload, _brand_ns(),
            )
        assert code == 1
        assert "Upload failed: router_unavailable" in out

    def test_json_envelope(self, cli):
        upload_result = {
            "uploaded_count": 2,
            "files": [
                {"asset": "logo", "file_id": "gid://1"},
                {"asset": "favicon", "file_id": "gid://2"},
            ],
            "missing_assets": [],
            "ok": True,
        }
        with patch(
            "engines.store_setup.brand_uploader."
            "upload_brand_assets",
            return_value=upload_result,
        ):
            out, code = _capture(
                cli._cmd_store_brand_upload,
                _brand_ns(json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert data["status"] == "ok"
        assert data["result"]["uploaded_count"] == 2
