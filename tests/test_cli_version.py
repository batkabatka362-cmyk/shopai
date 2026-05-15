"""Tests for ``shopai version`` — runtime fingerprint command.

A basic CLI hygiene gap. The version surface is also useful for
support: an operator reporting an issue can include their
ShopAI version + git SHA so we know what code they're running.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
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
    with patch("sys.stdout", buf):
        fn(*args, **kwargs)
    return buf.getvalue()


# ─── _build_version_dict ─────────────────────────────────────────


class TestBuildVersionDict:

    def test_required_keys_present(self, cli):
        payload = cli._build_version_dict()
        for key in ("shopai", "python", "platform"):
            assert key in payload

    def test_shopai_version_format(self, cli):
        """ShopAI version is semver-style (major.minor.patch).
        Future bumps shouldn't break this format."""
        payload = cli._build_version_dict()
        parts = payload["shopai"].split(".")
        assert len(parts) == 3
        # All parts numeric
        for p in parts:
            assert p.isdigit()

    def test_git_sha_when_in_repo(self, cli):
        """Running inside a git repo includes git_sha."""
        payload = cli._build_version_dict()
        # We ARE in a git repo (the test runs from one), so:
        assert "git_sha" in payload
        assert payload["git_sha"]  # non-empty
        # Short SHA is 7+ chars
        assert len(payload["git_sha"]) >= 7

    def test_no_git_sha_when_subprocess_fails(self, cli):
        """Outside a git repo (or git unavailable) → no git_sha
        key, no crash."""
        with patch(
            "subprocess.run",
            side_effect=OSError("git not found"),
        ):
            payload = cli._build_version_dict()
        assert "git_sha" not in payload
        # Required keys still present
        assert payload["shopai"]

    def test_no_git_sha_when_outside_repo(self, cli):
        """Subprocess returns non-zero (not a git repo) → no
        git_sha."""
        fake_result = subprocess.CompletedProcess(
            args=[], returncode=128, stdout="", stderr="fatal: not a git repo",
        )
        with patch("subprocess.run", return_value=fake_result):
            payload = cli._build_version_dict()
        assert "git_sha" not in payload

    def test_git_timeout_caught(self, cli):
        """A slow git invocation doesn't hang the version
        command — TimeoutExpired surfaces as missing git_sha."""
        with patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=[], timeout=2),
        ):
            payload = cli._build_version_dict()
        assert "git_sha" not in payload


# ─── _cmd_version ────────────────────────────────────────────────


class TestVersionCommand:

    def test_text_view(self, cli):
        out = _capture(
            cli._cmd_version,
            argparse.Namespace(json=False),
        )
        assert "ShopAI" in out
        assert "Python" in out
        assert "Platform" in out

    def test_json_view(self, cli):
        out = _capture(
            cli._cmd_version,
            argparse.Namespace(json=True),
        )
        data = json.loads(out)
        assert "shopai" in data
        assert "python" in data
        assert "platform" in data

    def test_json_view_is_parseable(self, cli):
        """JSON output is jq-friendly — first non-whitespace char
        is ``{``, no human-readable banner prefix."""
        out = _capture(
            cli._cmd_version,
            argparse.Namespace(json=True),
        )
        assert out.strip()[0] == "{"
        assert "ShopAI " not in out  # no text-view header in JSON


# ─── --full system identity ──────────────────────────────────


class TestFullFingerprint:

    def test_default_omits_system_identity_keys(self, cli):
        """Default (non-full) version dict should NOT include
        engine_count / dispatcher_count / scope_hash. Those
        fields are only added under --full so the default
        command stays cheap."""
        payload = cli._build_version_dict(full=False)
        assert "engine_count" not in payload
        assert "dispatcher_count" not in payload
        assert "scope_hash" not in payload

    def test_full_includes_system_identity_keys(self, cli):
        payload = cli._build_version_dict(full=True)
        # All identity blocks are present (may be None on
        # collector failure, but the keys exist)
        for key in (
            "engine_count",
            "dispatcher_count",
            "scope_count",
            "scope_hash",
            "engines_wired",
            "engines_advisory",
        ):
            assert key in payload

    def test_full_engine_count_matches_registry(self, cli):
        from engines.registry import engine_count
        payload = cli._build_version_dict(full=True)
        assert payload["engine_count"] == engine_count()

    def test_full_dispatcher_count_matches_registry(self, cli):
        from core.approval.executor import (
            list_registered_action_types,
            _ensure_dispatchers_loaded,
        )
        _ensure_dispatchers_loaded()
        payload = cli._build_version_dict(full=True)
        assert payload["dispatcher_count"] == len(
            list_registered_action_types(),
        )

    def test_full_scope_hash_stable_across_calls(self, cli):
        """Same code = same scope hash. Stable identity for
        support tickets."""
        a = cli._build_version_dict(full=True)
        b = cli._build_version_dict(full=True)
        assert a["scope_hash"] == b["scope_hash"]
        # Hash is a 12-char hex string (sha256 truncated)
        assert len(a["scope_hash"]) == 12

    def test_full_text_render_shows_identity(self, cli):
        out = _capture(
            cli._cmd_version,
            argparse.Namespace(json=False, full=True),
        )
        assert "System identity" in out
        assert "Engines:" in out
        assert "Dispatchers:" in out
        assert "Scopes:" in out

    def test_full_json_render_includes_identity(self, cli):
        out = _capture(
            cli._cmd_version,
            argparse.Namespace(json=True, full=True),
        )
        data = json.loads(out)
        assert "engine_count" in data
        assert "dispatcher_count" in data
        assert "scope_hash" in data

    def test_full_resilient_to_collector_failure(self, cli):
        """A single broken collector surfaces as ``None`` for
        its field, doesn't break the rest of the fingerprint."""
        with patch(
            "engines.registry.engine_count",
            side_effect=RuntimeError("broken"),
        ):
            payload = cli._build_version_dict(full=True)
        # engine_count is None, but the other fields still
        # populated
        assert payload["engine_count"] is None
        assert payload["dispatcher_count"] is not None
        assert payload["scope_hash"] is not None

    def test_default_text_render_omits_identity_block(self, cli):
        out = _capture(
            cli._cmd_version,
            argparse.Namespace(json=False, full=False),
        )
        assert "System identity" not in out
        assert "Dispatchers:" not in out
