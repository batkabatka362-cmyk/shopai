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
