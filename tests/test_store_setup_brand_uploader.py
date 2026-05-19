"""Tests for ``engines.store_setup.brand_uploader``.

Pushes brand asset URLs through ``SHOPIFY_UPLOAD_FILE`` and
records via Pattern Z. Measurable outcome: a store with
uploaded logo + favicon is launchable; without them it isn't.

Coverage:
  1. All four assets uploaded -> ok=True, no missing.
  2. Logo + favicon only (required minimum) -> ok=True.
  3. No URLs supplied -> ok=False with no_asset_urls_provided.
  4. Empty store_name -> early exit.
  5. Router unavailable -> records failure.
  6. Adapter rejection captured.
  7. Adapter raise captured.
  8. Alt-text -> asset label round-trip.
  9. Pattern Z recording shape.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.store_setup.brand_uploader import (
    _asset_from_alt,
    _build_alt,
    upload_brand_assets,
)


def _ok(files):
    return SimpleNamespace(
        ok=True,
        data={"uploaded": len(files), "files": files},
        error=None,
    )


def _fail(err: str):
    return SimpleNamespace(ok=False, data=None, error=err)


def _file(*, alt: str, file_id: str = "gid://1", url: str = ""):
    return {"id": file_id, "alt": alt, "preview_url": url}


# --- Alt-text convention --------------------------------------


class TestAltConvention:

    def test_round_trip_logo(self):
        alt = _build_alt("Acme", "logo")
        assert alt == "Acme logo"
        assert _asset_from_alt(alt) == "logo"

    def test_round_trip_favicon(self):
        alt = _build_alt("Acme Beauty", "favicon")
        assert _asset_from_alt(alt) == "favicon"

    def test_unknown_alt_returns_none(self):
        assert _asset_from_alt("random caption") is None

    def test_non_string_alt_returns_none(self):
        assert _asset_from_alt(None) is None
        assert _asset_from_alt(42) is None


# --- Validation -----------------------------------------------


class TestValidation:

    def test_empty_store_name(self):
        result = upload_brand_assets(
            store_name="",
            logo_url="https://example.com/logo.png",
        )
        assert result["ok"] is False
        assert result["error"] == "store_name_required"
        assert result["uploaded_count"] == 0

    def test_no_urls_supplied(self):
        result = upload_brand_assets(store_name="Acme")
        assert result["ok"] is False
        assert result["error"] == "no_asset_urls_provided"

    def test_whitespace_urls_ignored(self):
        result = upload_brand_assets(
            store_name="Acme",
            logo_url="   ",
            favicon_url="",
        )
        assert result["ok"] is False
        assert result["error"] == "no_asset_urls_provided"


# --- Successful uploads ---------------------------------------


class TestSuccessfulUploads:

    def test_full_asset_set(self):
        router = MagicMock()
        router.execute.return_value = _ok([
            _file(alt="Acme logo"),
            _file(alt="Acme favicon"),
            _file(alt="Acme hero"),
            _file(alt="Acme og_image"),
        ])
        with patch(
            "engines.store_setup.brand_uploader._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.brand_uploader."
            "record_writeback",
        ) as record_mock:
            result = upload_brand_assets(
                store_name="Acme",
                logo_url="https://x.com/logo.png",
                favicon_url="https://x.com/favicon.ico",
                hero_url="https://x.com/hero.jpg",
                og_image_url="https://x.com/og.png",
            )
        assert result["ok"] is True
        assert result["uploaded_count"] == 4
        assert result["missing_assets"] == []
        # Each file dict has the right asset label
        labels = {f["asset"] for f in result["files"]}
        assert labels == {
            "logo", "favicon", "hero", "og_image",
        }
        # Pattern Z recorded success
        record_mock.assert_called_once()
        assert record_mock.call_args.kwargs["success"] is True

    def test_logo_and_favicon_only_still_ok(self):
        router = MagicMock()
        router.execute.return_value = _ok([
            _file(alt="Acme logo"),
            _file(alt="Acme favicon"),
        ])
        with patch(
            "engines.store_setup.brand_uploader._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.brand_uploader."
            "record_writeback",
        ):
            result = upload_brand_assets(
                store_name="Acme",
                logo_url="https://x.com/logo.png",
                favicon_url="https://x.com/favicon.ico",
            )
        # Required minimum: ok=True even without hero/og
        assert result["ok"] is True
        assert "hero" in result["missing_assets"]
        assert "og_image" in result["missing_assets"]

    def test_missing_logo_makes_not_ok(self):
        """The minimum viable set is logo + favicon. Missing
        the logo means the storefront has no brand identity ->
        ok=False even if favicon uploaded."""
        router = MagicMock()
        router.execute.return_value = _ok([
            _file(alt="Acme favicon"),
        ])
        with patch(
            "engines.store_setup.brand_uploader._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.brand_uploader."
            "record_writeback",
        ):
            result = upload_brand_assets(
                store_name="Acme",
                favicon_url="https://x.com/favicon.ico",
            )
        assert result["ok"] is False
        assert "logo" in result["missing_assets"]


# --- Failure modes --------------------------------------------


class TestFailureModes:

    def test_router_unavailable_records_failure(self):
        with patch(
            "engines.store_setup.brand_uploader._get_router",
            return_value=None,
        ), patch(
            "engines.store_setup.brand_uploader."
            "record_writeback",
        ) as record_mock:
            result = upload_brand_assets(
                store_name="Acme",
                logo_url="https://x.com/logo.png",
            )
        assert result["ok"] is False
        assert result["error"] == "router_unavailable"
        assert record_mock.call_args.kwargs["success"] is False

    def test_adapter_rejection(self):
        router = MagicMock()
        router.execute.return_value = _fail("rate limited")
        with patch(
            "engines.store_setup.brand_uploader._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.brand_uploader."
            "record_writeback",
        ) as record_mock:
            result = upload_brand_assets(
                store_name="Acme",
                logo_url="https://x.com/logo.png",
            )
        assert result["ok"] is False
        assert "rate limited" in result["error"]
        assert record_mock.call_args.kwargs["success"] is False

    def test_adapter_raise(self):
        router = MagicMock()
        router.execute.side_effect = RuntimeError("network")
        with patch(
            "engines.store_setup.brand_uploader._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.brand_uploader."
            "record_writeback",
        ) as record_mock:
            result = upload_brand_assets(
                store_name="Acme",
                logo_url="https://x.com/logo.png",
            )
        assert result["ok"] is False
        assert "adapter_raise" in result["error"]
        assert "network" in result["error"]
        assert record_mock.call_args.kwargs["success"] is False


# --- Pattern Z recording shape --------------------------------


class TestPatternZRecording:

    def test_recorded_metrics_carry_counts(self):
        router = MagicMock()
        router.execute.return_value = _ok([
            _file(alt="Acme logo"),
            _file(alt="Acme favicon"),
        ])
        with patch(
            "engines.store_setup.brand_uploader._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.brand_uploader."
            "record_writeback",
        ) as record_mock:
            upload_brand_assets(
                store_name="Acme",
                logo_url="https://x.com/l.png",
                favicon_url="https://x.com/f.ico",
            )
        kwargs = record_mock.call_args.kwargs
        assert kwargs["engine"] == "store_setup"
        assert kwargs["action_type"] == "upload_brand_assets"
        assert kwargs["capability"] == "SHOPIFY_UPLOAD_FILE"
        assert kwargs["metrics"]["uploaded_count"] == 2
        # hero + og_image still missing
        missing = kwargs["metrics"]["missing_assets"]
        assert "hero" in missing
        assert "og_image" in missing

    def test_store_id_propagation(self):
        router = MagicMock()
        router.execute.return_value = _ok([
            _file(alt="Acme logo"),
            _file(alt="Acme favicon"),
        ])
        with patch(
            "engines.store_setup.brand_uploader._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.brand_uploader."
            "record_writeback",
        ) as record_mock:
            upload_brand_assets(
                store_name="Acme",
                logo_url="https://x.com/l.png",
                favicon_url="https://x.com/f.ico",
                store_id="store-a",
            )
        params = record_mock.call_args.kwargs["params"]
        assert params["store_id"] == "store-a"


# --- Adapter integration shape --------------------------------


class TestAdapterCallShape:

    def test_files_input_has_alt_per_asset(self):
        router = MagicMock()
        router.execute.return_value = _ok([
            _file(alt="Acme logo"),
            _file(alt="Acme favicon"),
        ])
        with patch(
            "engines.store_setup.brand_uploader._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.brand_uploader."
            "record_writeback",
        ):
            upload_brand_assets(
                store_name="Acme",
                logo_url="https://x.com/l.png",
                favicon_url="https://x.com/f.ico",
            )
        # The adapter was called with files=[{url, alt, type}]
        call_params = router.execute.call_args.args[1]
        files_arg = call_params["files"]
        alts = {f["alt"] for f in files_arg}
        assert "Acme logo" in alts
        assert "Acme favicon" in alts
