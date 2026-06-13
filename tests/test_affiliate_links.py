"""Tests for engines.affiliate_links — W963-9."""
from __future__ import annotations

from engines.affiliate_links import AffiliateLinksEngine
from engines.affiliate_links.code_generator import (
    build_link,
    generate_code,
)


# ── Code generator ─────────────────────────────────────────


class TestGenerateCode:
    def test_deterministic_same_email_same_code(self):
        a = generate_code("mary@example.com")
        b = generate_code("mary@example.com")
        assert a == b
        assert len(a) == 6

    def test_different_emails_different_codes(self):
        a = generate_code("mary@example.com")
        b = generate_code("alice@example.com")
        assert a != b

    def test_case_insensitive(self):
        a = generate_code("Mary@Example.COM")
        b = generate_code("mary@example.com")
        assert a == b

    def test_whitespace_stripped(self):
        a = generate_code("  mary@example.com  ")
        b = generate_code("mary@example.com")
        assert a == b

    def test_empty_returns_empty(self):
        assert generate_code("") == ""
        assert generate_code(None) == ""  # type: ignore[arg-type]

    def test_code_uses_only_alphabet_chars(self):
        for ident in ("a@b.com", "Foo Bar", "x"):
            code = generate_code(ident)
            # Alphabet excludes 0/O/1/I.
            assert "0" not in code
            assert "O" not in code
            assert "1" not in code
            assert "I" not in code


# ── Link builder ──────────────────────────────────────────


class TestBuildLink:
    def test_inserts_https_when_missing(self):
        link = build_link("store.myshopify.com", "ABC123")
        assert link.startswith("https://")
        assert "?ref=ABC123" in link

    def test_preserves_existing_protocol(self):
        link = build_link("http://localhost", "X")
        assert link.startswith("http://")

    def test_uses_amp_when_query_already_present(self):
        link = build_link(
            "https://store.com/?utm=facebook", "ABC",
        )
        assert "&ref=ABC" in link
        assert "utm=facebook" in link

    def test_empty_code_yields_empty(self):
        assert build_link("store.com", "") == ""

    def test_empty_shop_yields_empty(self):
        assert build_link("", "ABC") == ""

    def test_trailing_slash_stripped(self):
        link = build_link("https://store.com/", "X")
        assert link == "https://store.com?ref=X"


# ── Engine Pattern Q envelope ──────────────────────────────


class TestEngineEnvelope:
    def test_empty_input_error(self):
        # Empty input has no partner identity → error.
        result = AffiliateLinksEngine().run({})
        assert result["status"] == "error"

    def test_non_dict_error(self):
        result = AffiliateLinksEngine().run("nope")
        assert result["status"] == "error"

    def test_fail_upstream_short_circuits(self):
        result = AffiliateLinksEngine().run({
            "status": "fail", "error": "broken",
        })
        assert result["status"] == "error"

    def test_missing_identity_error(self):
        result = AffiliateLinksEngine().run({
            "data": {"shop_url": "store.myshopify.com"},
        })
        assert result["status"] == "error"
        assert "partner" in (result["error"] or "")

    def test_missing_shop_url_error(self):
        result = AffiliateLinksEngine().run({
            "data": {"partner_email": "x@example.com"},
        })
        assert result["status"] == "error"
        assert "shop_url" in (result["error"] or "")


# ── Engine happy path ──────────────────────────────────────


class TestEngineHappyPath:
    def test_email_identity_yields_link(self):
        result = AffiliateLinksEngine().run({
            "data": {
                "partner_email": "mary@example.com",
                "shop_url": "store.myshopify.com",
            },
        })
        assert result["status"] == "success"
        data = result["data"]
        assert data["code"]
        assert "?ref=" in data["link"]
        assert data["partner_email"] == "mary@example.com"

    def test_name_only_identity_works(self):
        result = AffiliateLinksEngine().run({
            "data": {
                "partner_name": "Mary",
                "shop_url": "store.myshopify.com",
            },
        })
        assert result["status"] == "success"
        assert result["data"]["code"]

    def test_email_preferred_over_name(self):
        # Same name but different emails -> different codes
        # (since email is the preferred identity source).
        r1 = AffiliateLinksEngine().run({
            "data": {
                "partner_email": "a@example.com",
                "partner_name": "Mary",
                "shop_url": "s.myshopify.com",
            },
        })
        r2 = AffiliateLinksEngine().run({
            "data": {
                "partner_email": "b@example.com",
                "partner_name": "Mary",
                "shop_url": "s.myshopify.com",
            },
        })
        assert r1["data"]["code"] != r2["data"]["code"]

    def test_idempotent_across_runs(self):
        params = {
            "data": {
                "partner_email": "x@example.com",
                "shop_url": "s.myshopify.com",
            },
        }
        a = AffiliateLinksEngine().run(params)
        b = AffiliateLinksEngine().run(params)
        assert a["data"]["code"] == b["data"]["code"]
        assert a["data"]["link"] == b["data"]["link"]
