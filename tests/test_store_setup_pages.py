"""Tests for ``engines.store_setup.page_generator`` +
``page_applier``.

Together these cover the standard storefront page setup flow:
generate 4 HTML bodies (About / Contact / FAQ / Shipping &
Returns) -> push through ``SHOPIFY_CREATE_PAGE`` adapter ->
record via Pattern Z.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.store_setup.page_generator import generate_pages
from engines.store_setup.page_applier import (
    _slug,
    apply_pages,
)


def _ok_result():
    return SimpleNamespace(ok=True, data={}, error=None)


def _fail_result(error: str):
    return SimpleNamespace(ok=False, data=None, error=error)


# --- generate_pages -------------------------------------------


class TestGeneratePages:

    def test_returns_four_pages(self):
        out = generate_pages(store_name="Acme")
        assert set(out.keys()) == {
            "About", "Contact", "FAQ", "Shipping & Returns",
        }

    def test_bodies_non_empty_html(self):
        out = generate_pages(store_name="Acme")
        for title, body in out.items():
            assert isinstance(body, str)
            assert body.startswith("<h1>")
            assert len(body) > 100

    def test_store_name_interpolated(self):
        out = generate_pages(store_name="Acme")
        for body in out.values():
            assert "Acme" in body

    def test_empty_store_name(self):
        assert generate_pages(store_name="") == {}
        assert generate_pages(store_name="   ") == {}
        assert generate_pages(store_name=None) == {}

    def test_niche_specific_tagline(self):
        beauty = generate_pages(
            store_name="Acme", niche="beauty",
        )
        assert "Clean beauty" in beauty["About"]
        fashion = generate_pages(
            store_name="Acme", niche="fashion",
        )
        assert "Curated fashion" in fashion["About"]

    def test_unknown_niche_falls_back(self):
        out = generate_pages(
            store_name="Acme", niche="ufo_parts",
        )
        # general fallback
        assert "Quality products" in out["About"]

    def test_founder_name_threaded_into_about(self):
        out = generate_pages(
            store_name="Acme",
            founder_name="Jane Doe",
        )
        assert "Jane Doe" in out["About"]

    def test_no_founder_uses_brand_only(self):
        out = generate_pages(store_name="Acme")
        # Brand-only origin sentence renders without founder name
        assert "Acme was founded" in out["About"]

    def test_faq_refund_window_per_niche(self):
        fashion = generate_pages(
            store_name="Acme", niche="fashion",
        )
        assert "14 days" in fashion["FAQ"]
        food = generate_pages(
            store_name="Acme", niche="food",
        )
        assert "no returns" in food["FAQ"]


class TestSupportEmail:
    """The Contact page must NEVER ship a placeholder
    mailto. Either a real email is rendered, or the page
    falls back to the contact form link.
    """

    def test_real_email_rendered_as_mailto(self):
        out = generate_pages(
            store_name="Acme",
            support_email="hello@acmestore.com",
        )
        contact = out["Contact"]
        assert (
            "<a href=\"mailto:hello@acmestore.com\">"
            in contact
        )
        assert "hello@acmestore.com" in contact
        # Placeholder must NOT be present
        assert "support@example.com" not in contact

    def test_no_email_falls_back_to_form(self):
        out = generate_pages(store_name="Acme")
        contact = out["Contact"]
        # No mailto attempted -- the form link is shown
        assert "mailto:" not in contact
        assert "/pages/contact" in contact
        # Placeholder must NEVER appear, even without input
        assert "example.com" not in contact

    def test_placeholder_email_rejected(self):
        """example.com / test.com / localhost domains are
        all silently swapped for the contact form link."""
        for bad in (
            "support@example.com",
            "noreply@example.org",
            "test@test.com",
            "x@localhost",
            "invalid@invalid",
        ):
            out = generate_pages(
                store_name="Acme", support_email=bad,
            )
            contact = out["Contact"]
            assert "mailto:" not in contact, bad
            assert bad not in contact, bad
            assert "/pages/contact" in contact, bad

    def test_malformed_email_rejected(self):
        out = generate_pages(
            store_name="Acme", support_email="not-an-email",
        )
        assert "mailto:" not in out["Contact"]

    def test_blank_email_falls_back(self):
        for blank in ("", "   ", None):
            out = generate_pages(
                store_name="Acme", support_email=blank,
            )
            assert "mailto:" not in out["Contact"]


# --- slug -----------------------------------------------------


class TestSlug:

    def test_basic_titles(self):
        assert _slug("About") == "about"
        assert _slug("Contact Us") == "contact-us"
        assert (
            _slug("Shipping & Returns") == "shipping-returns"
        )
        assert _slug("FAQ") == "faq"

    def test_strips_leading_trailing_hyphens(self):
        assert _slug("--About--") == "about"

    def test_empty_falls_back_to_page(self):
        assert _slug("") == "page"
        assert _slug("   ") == "page"
        assert _slug("---") == "page"


# --- apply_pages ----------------------------------------------


class TestApplyPagesEmpty:

    def test_empty_dict(self):
        out = apply_pages({})
        assert out == {"applied_count": 0, "results": []}

    def test_non_dict(self):
        out = apply_pages(None)  # type: ignore[arg-type]
        assert out == {"applied_count": 0, "results": []}


class TestApplyPagesSuccess:

    def test_all_pages_applied(self):
        router = MagicMock()
        router.execute.return_value = _ok_result()
        with patch(
            "engines.store_setup.page_applier._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.page_applier."
            "record_writeback",
        ) as record_mock:
            out = apply_pages({
                "About": "<h1>A</h1>",
                "Contact": "<h1>C</h1>",
            })
        assert out["applied_count"] == 2
        # Handles derived from titles
        results_by_title = {
            r["title"]: r for r in out["results"]
        }
        assert results_by_title["About"]["handle"] == "about"
        assert results_by_title["Contact"]["handle"] == "contact"
        # All succeeded -> all recorded as success
        assert record_mock.call_count == 2
        for call in record_mock.call_args_list:
            assert call.kwargs["success"] is True


class TestApplyPagesFailureModes:

    def test_router_unavailable(self):
        with patch(
            "engines.store_setup.page_applier._get_router",
            return_value=None,
        ), patch(
            "engines.store_setup.page_applier."
            "record_writeback",
        ) as record_mock:
            out = apply_pages({
                "About": "<h1>A</h1>",
                "FAQ": "<h1>F</h1>",
            })
        assert out["applied_count"] == 0
        assert all(
            r["error"] == "router_unavailable"
            for r in out["results"]
        )
        # Each page still recorded as a failure
        assert record_mock.call_count == 2

    def test_partial_failure(self):
        def _by_title(cap, params):
            if params["title"] == "FAQ":
                return _fail_result("title taken")
            return _ok_result()

        router = MagicMock()
        router.execute.side_effect = _by_title
        with patch(
            "engines.store_setup.page_applier._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.page_applier."
            "record_writeback",
        ):
            out = apply_pages({
                "About": "<h1>A</h1>",
                "FAQ": "<h1>F</h1>",
                "Contact": "<h1>C</h1>",
            })
        assert out["applied_count"] == 2
        by_title = {r["title"]: r for r in out["results"]}
        assert by_title["About"]["ok"] is True
        assert by_title["FAQ"]["ok"] is False
        assert "title taken" in by_title["FAQ"]["error"]
        assert by_title["Contact"]["ok"] is True

    def test_adapter_raise(self):
        router = MagicMock()
        router.execute.side_effect = RuntimeError("network")
        with patch(
            "engines.store_setup.page_applier._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.page_applier."
            "record_writeback",
        ):
            out = apply_pages({"About": "<h1>A</h1>"})
        assert out["applied_count"] == 0
        assert "network" in out["results"][0]["error"]


class TestStoreIdPropagation:

    def test_store_id_in_recorded_params(self):
        router = MagicMock()
        router.execute.return_value = _ok_result()
        with patch(
            "engines.store_setup.page_applier._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.page_applier."
            "record_writeback",
        ) as record_mock:
            apply_pages(
                {"About": "<h1>A</h1>"},
                store_id="store-a",
            )
        params = record_mock.call_args.kwargs["params"]
        assert params["store_id"] == "store-a"
