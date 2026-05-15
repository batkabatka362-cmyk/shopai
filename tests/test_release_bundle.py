"""Tests for ``shopai release-bundle`` -- the deploy-day capstone
that generates every release artifact (snapshot + catalog.md +
shopify.app.toml + doctor.txt + README.md) into one folder.

Tests cover:
  - Happy path: doctor passes -> 5 files emitted with the
    expected content
  - Doctor failure -> refuses to write the bundle (exit 1, no
    files created)
  - --write-on-warning + doctor failure -> emits anyway
  - Existing non-empty output dir without --force -> refused
  - --force overwrites existing files
  - Empty existing dir is OK (mkdir succeeds without --force)
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from io import StringIO
from pathlib import Path
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


def _ns(tmp_path, **kw):
    defaults = dict(
        output=str(tmp_path / "release"),
        app_name="shopai",
        app_host="https://shopai.test",
        api_version="2024-01",
        force=False,
        skip_live=True,
        write_on_warning=False,
        # Doctor-section collector args
        stale_pending_hours=24.0,
        failure_rate_warn=0.25,
        json=False,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


# ─── Happy path ──────────────────────────────────────────────


class TestHappyPath:

    def test_passing_doctor_writes_5_artifacts(self, cli, tmp_path):
        target = tmp_path / "release"
        out, code = _capture(
            cli._cmd_release_bundle, _ns(tmp_path, output=str(target)),
        )
        assert code == 0
        # All five files exist
        for name in (
            "snapshot.json",
            "catalog.md",
            "shopify.app.toml",
            "doctor.txt",
            "README.md",
        ):
            assert (target / name).exists(), f"{name} not created"
        # Stdout reports each file written
        assert "wrote" in out
        assert "snapshot.json" in out
        assert "catalog.md" in out
        assert "shopify.app.toml" in out

    def test_snapshot_json_is_valid(self, cli, tmp_path):
        target = tmp_path / "release"
        _capture(
            cli._cmd_release_bundle, _ns(tmp_path, output=str(target)),
        )
        data = json.loads(
            (target / "snapshot.json").read_text(encoding="utf-8"),
        )
        # Same shape as `shopai snapshot --output`
        assert data["schema_version"] == 1
        assert "engine_counts" in data
        assert "catalog" in data

    def test_catalog_md_is_markdown(self, cli, tmp_path):
        target = tmp_path / "release"
        _capture(
            cli._cmd_release_bundle, _ns(tmp_path, output=str(target)),
        )
        body = (target / "catalog.md").read_text(encoding="utf-8")
        # Top-level header from the Markdown render
        assert "# ShopAI Action Catalog" in body
        # ToC anchor for a known action
        assert "[`apply_tags`]" in body

    def test_app_toml_carries_app_host(self, cli, tmp_path):
        target = tmp_path / "release"
        _capture(
            cli._cmd_release_bundle,
            _ns(tmp_path, output=str(target),
                app_host="https://my.shopai.io"),
        )
        body = (target / "shopify.app.toml").read_text(
            encoding="utf-8",
        )
        assert "my.shopai.io" in body
        assert "[access_scopes]" in body

    def test_readme_links_artifacts(self, cli, tmp_path):
        target = tmp_path / "release"
        _capture(
            cli._cmd_release_bundle, _ns(tmp_path, output=str(target)),
        )
        body = (target / "README.md").read_text(encoding="utf-8")
        # Each artifact name appears as a link
        assert "snapshot.json" in body
        assert "catalog.md" in body
        assert "shopify.app.toml" in body
        assert "doctor.txt" in body
        # Doctor verdict line
        assert "Doctor verdict" in body

    def test_doctor_txt_is_text_render(self, cli, tmp_path):
        target = tmp_path / "release"
        _capture(
            cli._cmd_release_bundle, _ns(tmp_path, output=str(target)),
        )
        body = (target / "doctor.txt").read_text(encoding="utf-8")
        # The same headers the interactive doctor shows
        assert "ShopAI Shopify Doctor" in body
        assert "Pattern K dispatchers" in body
        assert "Overall" in body


# ─── Doctor failure gate ─────────────────────────────────────


class TestFailureGate:

    def test_doctor_failure_refuses_bundle(self, cli, tmp_path):
        target = tmp_path / "release"

        def _fake_collect(args):
            return False, {
                "pattern_k_dispatchers": {
                    "status": "fail",
                    "missing": ["x"],
                    "orphaned": [],
                    "enqueue_sites": 1,
                    "dispatchers_registered": 0,
                },
                "oauth_scope_coverage": {"status": "pass"},
                "pattern_y_capabilities": {"status": "pass"},
                "pattern_i_engine_capabilities": {"status": "pass"},
                "pattern_j_test_pollution": {"status": "pass"},
                "pattern_z_writer_recorder": {"status": "pass"},
                "live_scope_drift": {"status": "skipped"},
                "live_webhook_drift": {"status": "skipped"},
                "engines_writebacks": {"status": "info"},
            }

        with patch.object(cli, "_collect_doctor_sections", _fake_collect):
            out, code = _capture(
                cli._cmd_release_bundle,
                _ns(tmp_path, output=str(target)),
            )
        assert code == 1
        # No artifacts created
        assert not (target / "snapshot.json").exists()
        # Hint to override
        assert "--write-on-warning" in out

    def test_write_on_warning_emits_anyway(self, cli, tmp_path):
        target = tmp_path / "release"

        def _fake_collect(args):
            return False, {
                "pattern_k_dispatchers": {"status": "pass"},
                "oauth_scope_coverage": {"status": "pass"},
                "pattern_y_capabilities": {"status": "pass"},
                "pattern_i_engine_capabilities": {"status": "pass"},
                "pattern_j_test_pollution": {"status": "pass"},
                "pattern_z_writer_recorder": {"status": "pass"},
                "live_scope_drift": {
                    "status": "fail",
                    "missing_from_app": ["read_orders"],
                    "extra_in_app": [],
                },
                "live_webhook_drift": {"status": "skipped"},
                "engines_writebacks": {"status": "info"},
            }

        with patch.object(cli, "_collect_doctor_sections", _fake_collect):
            out, code = _capture(
                cli._cmd_release_bundle,
                _ns(tmp_path, output=str(target),
                    write_on_warning=True),
            )
        assert code == 0
        assert (target / "snapshot.json").exists()
        # The override message surfaces
        assert "--write-on-warning was passed" in out


# ─── Output directory handling ──────────────────────────────


class TestOutputDirHandling:

    def test_empty_existing_dir_accepted(self, cli, tmp_path):
        """An empty pre-existing directory is fine -- the bundle
        just writes into it."""
        target = tmp_path / "release"
        target.mkdir()
        out, code = _capture(
            cli._cmd_release_bundle, _ns(tmp_path, output=str(target)),
        )
        assert code == 0
        assert (target / "snapshot.json").exists()

    def test_nonempty_dir_refused_without_force(self, cli, tmp_path):
        target = tmp_path / "release"
        target.mkdir()
        (target / "old.txt").write_text("stale", encoding="utf-8")
        out, code = _capture(
            cli._cmd_release_bundle, _ns(tmp_path, output=str(target)),
        )
        assert code == 1
        # File untouched
        assert (target / "old.txt").read_text(encoding="utf-8") == "stale"
        # Bundle artifact NOT created
        assert not (target / "snapshot.json").exists()
        # Helpful message
        assert "--force" in out

    def test_nonempty_dir_overwritten_with_force(self, cli, tmp_path):
        target = tmp_path / "release"
        target.mkdir()
        # Use a non-conflicting sentinel since 'stale' legitimately
        # appears in snapshot.pending_queue's stale_threshold_hours
        # / stale_count fields.
        (target / "snapshot.json").write_text(
            "PRIOR_VERSION_SENTINEL", encoding="utf-8",
        )
        out, code = _capture(
            cli._cmd_release_bundle,
            _ns(tmp_path, output=str(target), force=True),
        )
        assert code == 0
        # Re-written with real JSON; the sentinel is gone
        body = (target / "snapshot.json").read_text(encoding="utf-8")
        assert "PRIOR_VERSION_SENTINEL" not in body
        data = json.loads(body)
        assert data["schema_version"] == 1

    def test_new_dir_created(self, cli, tmp_path):
        target = tmp_path / "nested" / "release"
        # Target doesn't exist
        assert not target.exists()
        out, code = _capture(
            cli._cmd_release_bundle, _ns(tmp_path, output=str(target)),
        )
        assert code == 0
        assert target.exists()
        assert (target / "snapshot.json").exists()
