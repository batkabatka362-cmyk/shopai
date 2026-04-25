"""Tests for scripts/deguar_bulk_images.py.

Monkeypatches ``_api`` + ``_fetch_all_products`` so tests never
hit the network. Covers:

  * config-file validation (wrong shape → rc 2)
  * ``--dry-run`` makes zero write calls
  * ``--min-images`` gate skips well-stocked products
  * ``--only`` pilots one product
  * ``--limit N`` caps the number of product-updates
  * existing image src is skipped (idempotency)
  * missing handle is surfaced but doesn't abort
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from scripts import deguar_bulk_images as mod


# ── Fixtures ───────────────────────────────────────────────


PRODUCTS = [
    {
        "id": 1, "title": "Galaxy Star Projector",
        "handle": "galaxy-star-projector-night-light",
        "status": "active", "images": [
            {"src": "https://cdn.shopify.com/existing.jpg"},
        ],
    },
    {
        "id": 2, "title": "Crystal Diffuser",
        "handle": "crystal-aromatherapy-oil-diffuser",
        "status": "active", "images": [
            {"src": "https://cdn.shopify.com/old-1.jpg"},
            {"src": "https://cdn.shopify.com/old-2.jpg"},
            {"src": "https://cdn.shopify.com/old-3.jpg"},
        ],
    },
    {
        "id": 3, "title": "Moon Lamp",
        "handle": "3d-moon-lamp-night-light",
        "status": "active", "images": [],
    },
]


@pytest.fixture(autouse=True)
def fake_store(monkeypatch):
    monkeypatch.setenv("SHOPAI_SHOPIFY_URL", "x.myshopify.com")
    monkeypatch.setenv("SHOPAI_SHOPIFY_KEY", "shpat_fake")
    monkeypatch.setattr(
        mod, "_fetch_all_products",
        lambda *, url, token: list(PRODUCTS),
    )


@pytest.fixture
def write_config(tmp_path):
    def _w(mapping):
        p = tmp_path / "cfg.json"
        p.write_text(json.dumps(mapping))
        return str(p)
    return _w


# ── Config validation ────────────────────────────────────


class TestConfigValidation:
    def test_missing_file_rc2(self, capsys):
        rc = mod.main([
            "--config", "/nonexistent/definitely-nope.json",
        ])
        assert rc == 2
        err = capsys.readouterr().err
        assert "cannot read config" in err

    def test_wrong_shape_rc2(self, tmp_path, capsys):
        p = tmp_path / "bad.json"
        p.write_text('[1,2,3]')  # list, not object
        rc = mod.main(["--config", str(p)])
        assert rc == 2
        err = capsys.readouterr().err
        assert "must be a JSON object" in err

    def test_only_unknown_handle_rc2(self, write_config, capsys):
        cfg = write_config({
            "galaxy-star-projector-night-light": ["https://a.jpg"],
        })
        rc = mod.main([
            "--config", cfg, "--only", "does-not-exist",
        ])
        assert rc == 2


# ── Dry-run makes no writes ───────────────────────────────


class TestDryRun:
    def test_zero_writes(self, write_config, capsys):
        calls: list[tuple] = []

        def fake_upload(*args, **kwargs):
            calls.append(args)
            return {"image": {"id": 1}}

        cfg = write_config({
            "galaxy-star-projector-night-light": [
                "https://a.jpg", "https://b.jpg",
            ],
            "3d-moon-lamp-night-light": [
                "https://c.jpg", "https://d.jpg", "https://e.jpg",
            ],
        })
        with patch.object(mod, "_upload", fake_upload):
            rc = mod.main([
                "--config", cfg, "--min-images", "3", "--dry-run",
            ])
        assert rc == 0
        assert calls == []  # zero real writes
        out = capsys.readouterr().out
        assert "DRY-RUN" in out


# ── min-images skip ──────────────────────────────────────


class TestMinImagesSkip:
    def test_already_stocked_skipped(self, write_config):
        """Crystal Diffuser already has 3 images — --min-images=3
        must skip it."""
        uploaded: list[str] = []

        def fake_upload(pid, src, alt, *, url, token):
            uploaded.append(src)
            return {"image": {"src": src}}

        cfg = write_config({
            "crystal-aromatherapy-oil-diffuser": [
                "https://a.jpg", "https://b.jpg",
            ],
            "3d-moon-lamp-night-light": [
                "https://c.jpg", "https://d.jpg", "https://e.jpg",
            ],
        })
        with patch.object(mod, "_upload", fake_upload):
            rc = mod.main([
                "--config", cfg, "--min-images", "3",
            ])
        assert rc == 0
        # Crystal must NOT get any upload (already has 3)
        assert "https://a.jpg" not in uploaded
        assert "https://b.jpg" not in uploaded
        # Moon lamp needs 3, got 3 queued
        assert set(uploaded) == {
            "https://c.jpg", "https://d.jpg", "https://e.jpg",
        }

    def test_partial_top_up(self, write_config):
        """Galaxy has 1 image, min=3 → uploads 2 more."""
        uploaded: list[str] = []

        def fake_upload(pid, src, alt, *, url, token):
            uploaded.append(src)
            return {"image": {"src": src}}

        cfg = write_config({
            "galaxy-star-projector-night-light": [
                "https://a.jpg", "https://b.jpg", "https://c.jpg",
                "https://d.jpg",
            ],
        })
        with patch.object(mod, "_upload", fake_upload):
            rc = mod.main([
                "--config", cfg, "--min-images", "3",
            ])
        assert rc == 0
        # Needs 3 - 1 existing = 2 uploads
        assert uploaded == ["https://a.jpg", "https://b.jpg"]


# ── --only targeting ─────────────────────────────────────


class TestOnlyFlag:
    def test_only_processes_single_handle(self, write_config):
        uploaded: list[str] = []

        def fake_upload(pid, src, alt, *, url, token):
            uploaded.append((pid, src))
            return {"image": {"src": src}}

        cfg = write_config({
            "galaxy-star-projector-night-light": [
                "https://a.jpg", "https://b.jpg",
            ],
            "3d-moon-lamp-night-light": [
                "https://c.jpg", "https://d.jpg", "https://e.jpg",
            ],
        })
        with patch.object(mod, "_upload", fake_upload):
            mod.main([
                "--config", cfg, "--min-images", "3",
                "--only", "galaxy-star-projector-night-light",
            ])
        # Only galaxy product (id 1) should receive uploads
        assert {pid for pid, _ in uploaded} == {"1"}


# ── --limit caps updates ─────────────────────────────────


class TestLimit:
    def test_caps_products_updated(self, write_config):
        uploaded: list[tuple] = []

        def fake_upload(pid, src, alt, *, url, token):
            uploaded.append((pid, src))
            return {"image": {"src": src}}

        cfg = write_config({
            "galaxy-star-projector-night-light": ["https://a.jpg"],
            "3d-moon-lamp-night-light": ["https://b.jpg"],
        })
        with patch.object(mod, "_upload", fake_upload):
            mod.main([
                "--config", cfg, "--min-images", "3",
                "--limit", "1",
            ])
        # Only one product should be processed — first one in dict
        product_ids = {pid for pid, _ in uploaded}
        assert len(product_ids) == 1


# ── Idempotency: duplicate src skipped ───────────────────


class TestIdempotency:
    def test_duplicate_src_skipped(self, write_config):
        """The existing image on product 1 is
        https://cdn.shopify.com/existing.jpg — if the config
        tries to re-upload that same URL, the script must
        short-circuit rather than re-POSTing."""
        uploaded: list[str] = []

        def fake_upload(pid, src, alt, *, url, token):
            uploaded.append(src)
            return {"image": {"src": src}}

        cfg = write_config({
            "galaxy-star-projector-night-light": [
                "https://cdn.shopify.com/existing.jpg",
                "https://new.jpg",
            ],
        })
        with patch.object(mod, "_upload", fake_upload):
            mod.main([
                "--config", cfg, "--min-images", "3",
            ])
        # Duplicate skipped, new one uploaded
        assert "https://cdn.shopify.com/existing.jpg" not in uploaded
        assert "https://new.jpg" in uploaded


# ── Missing handle surfaced ──────────────────────────────


class TestMissingHandle:
    def test_unknown_handle_warns_but_continues(
        self, write_config, capsys,
    ):
        uploaded: list[str] = []

        def fake_upload(pid, src, alt, *, url, token):
            uploaded.append(src)
            return {"image": {"src": src}}

        cfg = write_config({
            "not-in-store": ["https://ghost.jpg"],
            "3d-moon-lamp-night-light": ["https://real.jpg"],
        })
        with patch.object(mod, "_upload", fake_upload):
            rc = mod.main([
                "--config", cfg, "--min-images", "3",
            ])
        assert rc == 0
        out = capsys.readouterr().out
        assert "not-in-store" in out
        assert "not found" in out
        # Real handle still processed
        assert "https://real.jpg" in uploaded


# ── Upload failure isolated ──────────────────────────────


class TestErrorIsolation:
    def test_one_upload_fails_rest_continue(
        self, write_config, capsys,
    ):
        uploaded: list[str] = []
        seq: list[str] = []

        def fake_upload(pid, src, alt, *, url, token):
            seq.append(src)
            if src == "https://bad.jpg":
                raise RuntimeError("bad gateway")
            uploaded.append(src)
            return {"image": {"src": src}}

        cfg = write_config({
            "3d-moon-lamp-night-light": [
                "https://ok1.jpg", "https://bad.jpg",
                "https://ok2.jpg",
            ],
        })
        with patch.object(mod, "_upload", fake_upload):
            rc = mod.main([
                "--config", cfg, "--min-images", "3",
            ])
        assert rc == 0
        # All three attempted
        assert set(seq) == {
            "https://ok1.jpg", "https://bad.jpg",
            "https://ok2.jpg",
        }
        # Only good ones recorded as success
        assert set(uploaded) == {
            "https://ok1.jpg", "https://ok2.jpg",
        }
        out = capsys.readouterr().out
        assert "errors" in out.lower()
