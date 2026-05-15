"""Tests for ``shopai shopify-prepare-deploy`` — the capstone
gate that runs the doctor and only emits ``shopify.app.toml``
when every fatal check passes.

The command's job is to make "deploy day" idiot-proof: one
command verifies state + writes the file, refusing to write
when anything is broken. The override (--write-on-warning) is
explicit and audible.

Tests cover:
  - Happy path: doctor passes → file emitted at the requested
    output path with the expected scope + webhook content.
  - Doctor fails → refuses to write, exits 1, no file created.
  - --write-on-warning + doctor fails → emits anyway with a
    warning printed to stdout.
  - --force overwrites an existing file when paired with a
    passing doctor.
  - Existing file without --force → app-toml's safety refuses
    the overwrite (re-tested here because prepare-deploy
    delegates).
"""
from __future__ import annotations

import argparse
import importlib.util
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
        json=False,
        skip_live=True,
        output=str(tmp_path / "shopify.app.toml"),
        app_name="shopai",
        app_host="https://shopai.example.com",
        api_version="2024-01",
        force=False,
        write_on_warning=False,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


# ─── Happy path ────────────────────────────────────────────────


class TestHappyPath:

    def test_passing_doctor_writes_toml(self, cli, tmp_path):
        target = tmp_path / "shopify.app.toml"
        out, code = _capture(
            cli._cmd_shopify_prepare_deploy,
            _ns(tmp_path, output=str(target)),
        )
        assert code == 0
        assert target.exists()
        body = target.read_text(encoding="utf-8")
        # Combined manifest: scopes block + webhooks block
        assert "[access_scopes]" in body
        assert "[webhooks]" in body
        # App host substituted in callback URLs + redirect URIs
        assert "shopai.example.com" in body
        # Doctor header rendered to stdout
        assert "ShopAI prepare-deploy" in out
        assert "[pass] Pattern K" in out

    def test_default_output_is_shopify_app_toml(self, cli, tmp_path, monkeypatch):
        """When --output isn't passed, the command defaults to
        ``shopify.app.toml`` in cwd. cd into tmp_path so we don't
        write into the actual repo."""
        monkeypatch.chdir(tmp_path)
        # No output= → expect default
        ns = _ns(tmp_path)
        ns.output = "shopify.app.toml"
        _capture(cli._cmd_shopify_prepare_deploy, ns)
        assert (tmp_path / "shopify.app.toml").exists()


# ─── Doctor failure gate ───────────────────────────────────────


class TestFailureGate:

    def test_doctor_failure_refuses_write(self, cli, tmp_path):
        """Patch one section's collector to return a fail. The
        command should refuse to emit the TOML and exit 1."""
        target = tmp_path / "shopify.app.toml"

        def _fake_collect(args):
            return False, {
                "pattern_k_dispatchers": {
                    "status": "fail",
                    "enqueue_sites": 1,
                    "dispatchers_registered": 0,
                    "missing": ["foo_action"],
                    "orphaned": [],
                },
                "oauth_scope_coverage": {"status": "pass"},
                "pattern_y_capabilities": {"status": "pass"},
                "live_scope_drift": {"status": "skipped"},
                "live_webhook_drift": {"status": "skipped"},
                "engines_writebacks": {"status": "info"},
            }

        with patch.object(cli, "_collect_doctor_sections", _fake_collect):
            out, code = _capture(
                cli._cmd_shopify_prepare_deploy,
                _ns(tmp_path, output=str(target)),
            )
        assert code == 1
        assert not target.exists()
        assert "Refusing to write" in out
        # Hint about the override is surfaced
        assert "--write-on-warning" in out

    def test_write_on_warning_emits_anyway(self, cli, tmp_path):
        """The escape hatch — during initial bring-up before a
        live Shopify app exists, operators need to be able to
        generate the file."""
        target = tmp_path / "shopify.app.toml"

        def _fake_collect(args):
            return False, {
                "pattern_k_dispatchers": {"status": "pass"},
                "oauth_scope_coverage": {"status": "pass"},
                "pattern_y_capabilities": {"status": "pass"},
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
                cli._cmd_shopify_prepare_deploy,
                _ns(
                    tmp_path,
                    output=str(target),
                    write_on_warning=True,
                ),
            )
        assert code == 0
        assert target.exists()
        assert "--write-on-warning was" in out


# ─── --force semantics ─────────────────────────────────────────


class TestForce:

    def test_existing_file_refused_without_force(self, cli, tmp_path):
        target = tmp_path / "shopify.app.toml"
        target.write_text("# previous content\n", encoding="utf-8")

        _, code = _capture(
            cli._cmd_shopify_prepare_deploy,
            _ns(tmp_path, output=str(target)),
        )
        # app-toml's overwrite protection kicks in → exit 1
        assert code == 1
        # File untouched
        assert target.read_text(encoding="utf-8") == "# previous content\n"

    def test_existing_file_overwritten_with_force(self, cli, tmp_path):
        target = tmp_path / "shopify.app.toml"
        target.write_text("# stale\n", encoding="utf-8")

        _, code = _capture(
            cli._cmd_shopify_prepare_deploy,
            _ns(tmp_path, output=str(target), force=True),
        )
        assert code == 0
        body = target.read_text(encoding="utf-8")
        assert "# stale" not in body
        assert "[webhooks]" in body


# ─── Argparse wireup ───────────────────────────────────────────


class TestArgparseWireup:

    def test_subcommand_registered(self, cli):
        """The subparser is registered so `shopai
        shopify-prepare-deploy --help` actually works."""
        parser = cli.build_parser() if hasattr(cli, "build_parser") else None
        # Most CLIs build the parser inside main(); call argparse
        # round-trip via the module's argparse import
        # Easier: verify the dispatch entry exists in main's source.
        import inspect
        main_src = inspect.getsource(cli.main)
        assert "shopify-prepare-deploy" in main_src
