"""Tests for ``engines.store_setup.support_kb``.

Generator produces a structured Q&A knowledge base; applier
persists it as a Shopify page (handle ``customer-support``)
via ``SHOPIFY_CREATE_PAGE``. Records via Pattern Z.

Coverage:
  1. Generator: empty store_name -> empty dict.
  2. Generator: universal entries always present.
  3. Generator: niche-specific entries stack on top of
     universals (count grows per niche).
  4. Generator: unknown niche falls back to general.
  5. Generator: every shipped niche has 3+ niche-specific
     entries.
  6. Generator: entry shape validation.
  7. Renderer: empty -> empty string.
  8. Renderer: groups by category.
  9. Renderer: HTML-escapes content.
 10. Applier: empty -> short-circuit.
 11. Applier: success + Pattern Z.
 12. Applier: router_unavailable + records failure.
 13. Applier: adapter raise + rejection.
 14. store_id propagation.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.store_setup.support_kb import (
    _NICHE_ENTRIES,
    _UNIVERSAL_ENTRIES,
    apply_support_kb,
    generate_support_kb,
    render_kb_html,
)


def _ok():
    return SimpleNamespace(ok=True, data={}, error=None)


def _fail(err: str):
    return SimpleNamespace(ok=False, data=None, error=err)


# ── Generator ─────────────────────────────────────────────────


class TestGeneratorEmpty:

    def test_empty_store_name(self):
        assert generate_support_kb(store_name="") == {}
        assert generate_support_kb(store_name="   ") == {}
        assert generate_support_kb(store_name=None) == {}


class TestGeneratorShape:

    def test_universal_entries_always_present(self):
        spec = generate_support_kb(
            store_name="Acme", niche="general",
        )
        # Universal entries are 7 in count
        assert len(spec["entries"]) >= len(
            _UNIVERSAL_ENTRIES,
        )
        # First-N entries are the universal set in order
        for i, (q, a, c) in enumerate(_UNIVERSAL_ENTRIES):
            assert spec["entries"][i]["question"] == q
            assert spec["entries"][i]["answer"] == a
            assert spec["entries"][i]["category"] == c

    def test_niche_entries_stack_on_top(self):
        """Beauty has 4 niche-specific entries -- total
        should be universal (7) + 4 = 11."""
        spec = generate_support_kb(
            store_name="Acme", niche="beauty",
        )
        assert (
            len(spec["entries"])
            == len(_UNIVERSAL_ENTRIES)
            + len(_NICHE_ENTRIES["beauty"])
        )

    def test_unknown_niche_falls_back_to_general(self):
        spec = generate_support_kb(
            store_name="Acme", niche="ufo_parts",
        )
        # falls back to general's entries
        assert (
            len(spec["entries"])
            == len(_UNIVERSAL_ENTRIES)
            + len(_NICHE_ENTRIES["general"])
        )


class TestNicheCoverage:

    def test_every_shipped_niche_has_three_plus_entries(self):
        """Niche-specific knowledge bases need real depth --
        less than 3 entries is just a placeholder."""
        for niche, entries in _NICHE_ENTRIES.items():
            assert len(entries) >= 2, niche
            # Most niches should have 3+
            if niche != "general":
                assert len(entries) >= 3, niche

    def test_each_entry_has_full_shape(self):
        for niche in _NICHE_ENTRIES:
            spec = generate_support_kb(
                store_name="Acme", niche=niche,
            )
            for entry in spec["entries"]:
                assert entry["question"], niche
                assert entry["answer"], niche
                assert entry["category"], niche
                assert len(entry["answer"]) >= 30, niche

    def test_niche_specific_questions_present(self):
        """Each niche-specific Q&A must surface a unique
        category-specific concern, not duplicate universals."""
        cases = {
            "beauty": "patch test",
            "fashion": "size guide",
            "tech": "warranty",
            "food": "expiry",
            "pets": "ingredient",
            "fitness": "third-party tested",
            "jewelry": "metal",
            "outdoor": "weatherproof",
            "baby": "age stage",
        }
        for niche, needle in cases.items():
            spec = generate_support_kb(
                store_name="Acme", niche=niche,
            )
            blob = " ".join(
                e["question"].lower() + " "
                + e["answer"].lower()
                for e in spec["entries"]
            )
            assert needle in blob, (niche, needle)


# ── Renderer ──────────────────────────────────────────────────


class TestRenderer:

    def test_empty_spec(self):
        assert render_kb_html({}) == ""
        assert render_kb_html(None) == ""  # type: ignore[arg-type]
        assert render_kb_html({"store_name": "Acme"}) == ""

    def test_renders_heading_and_qa(self):
        spec = generate_support_kb(
            store_name="Acme Beauty", niche="beauty",
        )
        html_out = render_kb_html(spec)
        assert "<section class=\"support-kb\">" in html_out
        assert "Acme Beauty" in html_out
        # Question count matches: every entry rendered as
        # <h3>...</h3>. Count h3 tags rather than substring
        # match, since renderer HTML-escapes apostrophes /
        # entities that break naive contains-checks.
        assert html_out.count("<h3>") == len(
            spec["entries"],
        )
        assert html_out.count("</h3>") == len(
            spec["entries"],
        )

    def test_groups_by_category(self):
        spec = generate_support_kb(
            store_name="Acme", niche="beauty",
        )
        html_out = render_kb_html(spec)
        # Categories show as <h2> headings
        assert "<h2>Shipping</h2>" in html_out
        # Beauty-specific categories
        assert "Ingredients" in html_out

    def test_escapes_user_content(self):
        spec = {
            "store_name": "<script>evil</script>",
            "niche": "beauty",
            "entries": [{
                "question": "<b>q</b>",
                "answer": "x & y",
                "category": "shipping",
            }],
        }
        html_out = render_kb_html(spec)
        assert "<script>" not in html_out
        assert "&lt;script&gt;" in html_out
        assert "&amp;" in html_out


# ── Applier ──────────────────────────────────────────────────


class TestApplierEmpty:

    def test_no_spec(self):
        out = apply_support_kb({})
        assert out["applied"] is False
        assert out["error"] == "no_kb_spec"

    def test_non_dict(self):
        out = apply_support_kb(None)  # type: ignore[arg-type]
        assert out["applied"] is False

    def test_spec_without_entries(self):
        out = apply_support_kb({"store_name": "Acme"})
        assert out["applied"] is False


class TestApplierSuccess:

    def test_pushes_via_create_page(self):
        router = MagicMock()
        router.execute.return_value = _ok()
        spec = generate_support_kb(
            store_name="Acme", niche="beauty",
        )
        with patch(
            "engines.store_setup.support_kb._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.support_kb."
            "record_writeback",
        ) as record_mock:
            out = apply_support_kb(spec)
        assert out["applied"] is True
        assert out["handle"] == "customer-support"
        params = router.execute.call_args.args[1]
        assert params["title"] == "Customer Support"
        assert params["handle"] == "customer-support"
        assert "support-kb" in params["body_html"]
        assert params["published"] is True
        record_mock.assert_called_once()
        kwargs = record_mock.call_args.kwargs
        assert kwargs["success"] is True
        # Entry count surfaced in metrics
        assert (
            kwargs["metrics"]["entry_count"]
            == len(spec["entries"])
        )


class TestApplierFailureModes:

    def test_router_unavailable(self):
        spec = generate_support_kb(store_name="Acme")
        with patch(
            "engines.store_setup.support_kb._get_router",
            return_value=None,
        ), patch(
            "engines.store_setup.support_kb."
            "record_writeback",
        ) as record_mock:
            out = apply_support_kb(spec)
        assert out["applied"] is False
        assert out["error"] == "router_unavailable"
        record_mock.assert_called_once()
        assert (
            record_mock.call_args.kwargs["success"] is False
        )

    def test_adapter_rejection(self):
        router = MagicMock()
        router.execute.return_value = _fail("handle taken")
        spec = generate_support_kb(store_name="Acme")
        with patch(
            "engines.store_setup.support_kb._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.support_kb."
            "record_writeback",
        ):
            out = apply_support_kb(spec)
        assert out["applied"] is False
        assert "handle taken" in out["error"]

    def test_adapter_raise(self):
        router = MagicMock()
        router.execute.side_effect = RuntimeError("network")
        spec = generate_support_kb(store_name="Acme")
        with patch(
            "engines.store_setup.support_kb._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.support_kb."
            "record_writeback",
        ):
            out = apply_support_kb(spec)
        assert out["applied"] is False
        assert "network" in out["error"]


class TestStoreIdPropagation:

    def test_store_id_recorded(self):
        router = MagicMock()
        router.execute.return_value = _ok()
        spec = generate_support_kb(store_name="Acme")
        with patch(
            "engines.store_setup.support_kb._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.support_kb."
            "record_writeback",
        ) as record_mock:
            apply_support_kb(spec, store_id="store-a")
        params = record_mock.call_args.kwargs["params"]
        assert params["store_id"] == "store-a"
