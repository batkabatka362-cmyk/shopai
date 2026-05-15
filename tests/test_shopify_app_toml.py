"""Tests for ``shopai shopify-app-toml`` — combined emitter
that produces a complete ``shopify.app.toml`` from the
registries.
"""
from __future__ import annotations

import argparse
import importlib.util
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
    defaults = dict(
        app_name="shopai",
        app_host="https://YOUR_APP_HOST",
        api_version="2024-01",
        write=None,
        force=False,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


# ─── Output structure ──────────────────────────────────────────


class TestStructure:

    def test_emits_top_level_name_and_url(self, cli):
        out, code = _capture(
            cli._cmd_shopify_app_toml,
            _ns(app_name="myapp", app_host="https://example.com"),
        )
        assert code == 0
        assert 'name = "myapp"' in out
        assert 'application_url = "https://example.com/"' in out

    def test_emits_auth_section_with_callbacks(self, cli):
        out, _ = _capture(
            cli._cmd_shopify_app_toml,
            _ns(app_host="https://example.com"),
        )
        assert "[auth]" in out
        assert "https://example.com/auth/callback" in out
        assert "https://example.com/auth/shopify/callback" in out

    def test_emits_access_scopes_block(self, cli):
        out, _ = _capture(cli._cmd_shopify_app_toml, _ns())
        assert "[access_scopes]" in out
        assert 'scopes = "' in out
        # Live registry has read_orders + write_orders + ...
        assert "read_orders" in out
        assert "write_orders" in out

    def test_emits_webhooks_block(self, cli):
        out, _ = _capture(cli._cmd_shopify_app_toml, _ns())
        assert "[webhooks]" in out
        assert 'api_version = "2024-01"' in out
        # Every registered topic surfaces
        assert "orders/create" in out
        assert "customers/data_request" in out  # GDPR mandatory

    def test_api_version_substitution(self, cli):
        out, _ = _capture(
            cli._cmd_shopify_app_toml,
            _ns(api_version="2024-04"),
        )
        assert 'api_version = "2024-04"' in out


# ─── App host substitution ─────────────────────────────────────


class TestAppHostSubstitution:

    def test_default_placeholder(self, cli):
        out, _ = _capture(cli._cmd_shopify_app_toml, _ns())
        # Default = placeholder
        assert "YOUR_APP_HOST" in out

    def test_custom_host_propagates_to_callbacks(self, cli):
        out, _ = _capture(
            cli._cmd_shopify_app_toml,
            _ns(app_host="https://shopai.example.com"),
        )
        # Webhook URLs use the new host
        assert "https://shopai.example.com/api/webhook/shopify" in out
        # Auth redirects use the new host
        assert "https://shopai.example.com/auth/callback" in out

    def test_trailing_slash_stripped(self, cli):
        """Operators sometimes pass --app-host with a trailing
        slash; the emitter normalises it to avoid double-slash
        URLs like ``https://example.com//api/webhook/shopify``."""
        out, _ = _capture(
            cli._cmd_shopify_app_toml,
            _ns(app_host="https://example.com/"),
        )
        # No double slash in any callback line
        for line in out.splitlines():
            if "//api/webhook" in line or "//auth/callback" in line:
                raise AssertionError(
                    f"Double slash leaked: {line!r}"
                )
        # Single slash form is present
        assert "https://example.com/api/webhook/shopify" in out


# ─── Header ────────────────────────────────────────────────────


class TestHeader:

    def test_header_includes_counts(self, cli):
        out, _ = _capture(cli._cmd_shopify_app_toml, _ns())
        # Live counts in the header comment
        assert "OAuth scope(s)" in out
        assert "webhook subscription(s)" in out

    def test_header_mentions_regenerate_after_edit(self, cli):
        out, _ = _capture(cli._cmd_shopify_app_toml, _ns())
        assert "Re-run after any registry edit" in out


# ─── GDPR-mandatory subscriptions ──────────────────────────────


class TestGdprIncluded:

    def test_all_three_gdpr_topics_present(self, cli):
        """The combined emitter MUST include the three GDPR-
        mandatory topics — otherwise a Shopify review submission
        from this output would fail."""
        out, _ = _capture(cli._cmd_shopify_app_toml, _ns())
        for topic in (
            "customers/data_request",
            "customers/redact",
            "shop/redact",
        ):
            assert topic in out


# ─── Resilience ────────────────────────────────────────────────


class TestResilience:

    def test_scope_collect_failure_still_emits_skeleton(self, cli):
        """If the scope manifest fails to collect, the emitter
        still produces a usable file — just with no
        [access_scopes] block. Operators can fall back to hand-
        editing in that case."""
        with patch(
            "core.adapters.shopify.scope_registry.collect_manifest",
            side_effect=RuntimeError("scope broken"),
        ):
            out, code = _capture(cli._cmd_shopify_app_toml, _ns())
        assert code == 0
        # Webhooks block still emits even when scopes are
        # unavailable
        assert "[webhooks]" in out
        # Skeleton fields still present
        assert 'name = "shopai"' in out


# ─── --write extension ────────────────────────────────────────


class TestWriteToFile:
    """Tests for the --write FILE / --force flag combination.

    --write redirects the emitter's output from stdout to the
    given file. By default it refuses to clobber an existing
    file — operators have to pass --force to overwrite (protects
    against accidentally trampling a hand-edited
    shopify.app.toml).
    """

    def test_write_creates_file(self, cli, tmp_path):
        target = tmp_path / "shopify.app.toml"
        assert not target.exists()
        out, code = _capture(
            cli._cmd_shopify_app_toml,
            _ns(write=str(target)),
        )
        assert code == 0
        assert target.exists()
        body = target.read_text(encoding="utf-8")
        # Same content shape as stdout output
        assert 'name = "shopai"' in body
        assert "[access_scopes]" in body
        assert "[webhooks]" in body

    def test_write_status_line_to_stdout(self, cli, tmp_path):
        """When writing to a file, stdout shows a one-line
        status confirmation (not the file contents) — operators
        can tail / pipe / monitor the success without parsing
        a multi-line TOML."""
        target = tmp_path / "out.toml"
        out, _ = _capture(
            cli._cmd_shopify_app_toml,
            _ns(write=str(target)),
        )
        assert "Wrote" in out
        # Stats appear in the status line so operators
        # can sanity-check
        assert "scopes" in out
        assert "webhooks" in out

    def test_write_refuses_overwrite_without_force(
        self, cli, tmp_path,
    ):
        target = tmp_path / "exists.toml"
        target.write_text("PRE-EXISTING CONTENT", encoding="utf-8")
        out, code = _capture(
            cli._cmd_shopify_app_toml,
            _ns(write=str(target)),
        )
        assert code == 1
        assert "Refusing to overwrite" in out
        # File untouched
        assert target.read_text(encoding="utf-8") == "PRE-EXISTING CONTENT"

    def test_write_force_overwrites(self, cli, tmp_path):
        target = tmp_path / "exists.toml"
        target.write_text("PRE-EXISTING CONTENT", encoding="utf-8")
        out, code = _capture(
            cli._cmd_shopify_app_toml,
            _ns(write=str(target), force=True),
        )
        assert code == 0
        # File replaced
        new_body = target.read_text(encoding="utf-8")
        assert new_body != "PRE-EXISTING CONTENT"
        assert 'name = "shopai"' in new_body

    def test_write_creates_parent_dir(self, cli, tmp_path):
        """When the target's parent dir doesn't exist, the
        emitter creates it — operators pointing at e.g.
        ``deploy/shopify.app.toml`` don't fail on a missing
        dir."""
        target = tmp_path / "deploy" / "nested" / "app.toml"
        assert not target.parent.exists()
        out, code = _capture(
            cli._cmd_shopify_app_toml,
            _ns(write=str(target)),
        )
        assert code == 0
        assert target.exists()

    def test_write_file_ends_with_newline(self, cli, tmp_path):
        """Standard convention: text files end with a newline.
        Some tools (POSIX) strip the final line if it lacks one;
        Shopify's CLI parser handles either but emitting the
        newline is the polite default."""
        target = tmp_path / "newline.toml"
        _capture(
            cli._cmd_shopify_app_toml,
            _ns(write=str(target)),
        )
        body = target.read_bytes()
        assert body.endswith(b"\n")

    def test_stdout_mode_unchanged_when_no_write(
        self, cli, tmp_path,
    ):
        """Without --write, the emitter still writes to stdout
        like before — backwards compatible with PR #184."""
        out, code = _capture(cli._cmd_shopify_app_toml, _ns())
        assert code == 0
        # Full TOML in stdout
        assert 'name = "shopai"' in out
        assert "[access_scopes]" in out
        # No "Wrote" status line (which only appears in write mode)
        assert "Wrote" not in out

    def test_write_io_error_exits_1(self, cli, tmp_path):
        """Mock a write failure (read-only filesystem, etc.).
        Should exit 1 with an actionable error message rather
        than crashing."""
        from unittest.mock import patch as mock_patch
        target = tmp_path / "blocked.toml"
        with mock_patch(
            "pathlib.Path.write_text",
            side_effect=OSError("permission denied"),
        ):
            out, code = _capture(
                cli._cmd_shopify_app_toml,
                _ns(write=str(target)),
            )
        assert code == 1
        assert "Failed to write" in out
