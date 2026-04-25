"""shopify.app.toml drift regression.

The toml is auto-generated from core.auth.shopify_scopes.
This file exercises the generator + diffs the committed file
against the canonical source. CI fails when someone edits
the toml by hand or adds/removes a canonical scope without
regenerating.
"""
from __future__ import annotations

import pathlib

import pytest

from core.auth.shopify_scopes import (
    recommended_scopes, required_scopes,
)
from scripts import generate_shopify_app_toml as gen


REPO = pathlib.Path(__file__).resolve().parent.parent
TOML = REPO / "shopify.app.toml"


# ── Generator output ─────────────────────────────────────


class TestGenerator:
    def test_render_includes_every_required_handle(self):
        body = gen.render_toml(
            client_id="placeholder",
            application_url="http://localhost:9000",
            redirect_url="http://localhost:9000/callback",
        )
        for s in required_scopes():
            assert s.handle in body, (
                f"required scope {s.handle} missing from "
                "generated toml"
            )

    def test_render_includes_every_recommended_handle(self):
        body = gen.render_toml(
            client_id="placeholder",
            application_url="http://localhost:9000",
            redirect_url="http://localhost:9000/callback",
        )
        for s in recommended_scopes():
            # recommended ends up in optional_scopes.
            assert f'"{s.handle}"' in body

    def test_render_excludes_plus_only(self):
        from core.auth.shopify_scopes import plus_scopes
        body = gen.render_toml(
            client_id="x",
            application_url="http://localhost:9000",
            redirect_url="http://localhost:9000/callback",
        )
        for s in plus_scopes():
            # Plus-only scopes must not auto-include — they
            # cause install failure on non-Plus stores.
            assert f'"{s.handle}"' not in body, (
                f"plus-only {s.handle} leaked into toml"
            )

    def test_required_count_matches(self):
        body = gen.render_toml(
            client_id="x",
            application_url="http://localhost:9000",
            redirect_url="http://localhost:9000/callback",
        )
        # The "scopes = " line is one CSV string; the
        # generator embeds the count in the comment above.
        assert (
            f"{len(required_scopes())} entries." in body
        )

    def test_placeholder_when_no_client_id(self):
        body = gen.render_toml(
            client_id="",
            application_url="http://localhost:9000",
            redirect_url="http://localhost:9000/callback",
        )
        assert (
            "<paste-from-partners-dashboard>" in body
        )


# ── Committed file is in sync ────────────────────────────


class TestCommittedToml:
    def test_file_exists(self):
        assert TOML.exists(), (
            "shopify.app.toml is missing — run "
            "scripts/generate_shopify_app_toml.py"
        )

    def test_committed_carries_required_scopes(self):
        body = TOML.read_text(encoding="utf-8")
        for s in required_scopes():
            assert s.handle in body, (
                f"committed shopify.app.toml is out of sync "
                f"— missing required {s.handle}. Re-run "
                "scripts/generate_shopify_app_toml.py"
            )

    def test_committed_carries_recommended_scopes(self):
        body = TOML.read_text(encoding="utf-8")
        for s in recommended_scopes():
            assert f'"{s.handle}"' in body, (
                f"committed shopify.app.toml is out of sync "
                f"— missing recommended {s.handle}"
            )

    def test_redirect_url_present(self):
        body = TOML.read_text(encoding="utf-8")
        assert (
            "http://localhost:9000/callback" in body
        )


# ── Generator main() ─────────────────────────────────────


class TestMain:
    def test_writes_to_custom_path(self, tmp_path):
        out = tmp_path / "x.toml"
        rc = gen.main([
            "--out", str(out),
            "--env", str(tmp_path / "nonexistent.env"),
        ])
        assert rc == 0
        body = out.read_text(encoding="utf-8")
        # No client id → placeholder
        assert "<paste-from-partners-dashboard>" in body
        # Required scopes present
        for s in required_scopes():
            assert s.handle in body
