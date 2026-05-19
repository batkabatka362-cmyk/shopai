"""Tests for ``engines.store_setup.smart_collection_rules``.

Reference-data module: produces niche-aware smart-collection
specs ready for ``collection_seeder.apply_starter_collections``
which calls ``SHOPIFY_CREATE_COLLECTION`` with the
``rule_set`` arg.

Coverage:
  1. Generator: 4 universal collections always present.
  2. Generator: niche-specific stack on top of universal.
  3. Generator: each spec has the full shape (title, handle,
     description_html, sort_order, rule_set).
  4. Generator: rule_set has applied_disjunctively + rules.
  5. Generator: every shipped niche resolves.
  6. Generator: rules reference tag values from
     `tag_library` (cross-module consistency).
  7. Generator: sort_order values are valid Shopify enums.
  8. Generator: rule columns are valid Shopify enums.
  9. Generator: handles are slug-cased.
 10. Drop-in compat: spec shape works with
     `collection_seeder.apply_starter_collections`.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.store_setup.collection_seeder import (
    apply_starter_collections,
)
from engines.store_setup.smart_collection_rules import (
    _NICHE_COLLECTIONS,
    _UNIVERSAL_COLLECTIONS,
    _slug,
    generate_smart_collections,
)


# ── Generator shape ──────────────────────────────────────────


class TestGenerator:

    def test_universal_collections_always_present(self):
        spec = generate_smart_collections(niche="general")
        assert (
            len(spec["collections"])
            == len(_UNIVERSAL_COLLECTIONS)
        )
        # In order: New Arrivals, On Sale, In Stock,
        # Under $50
        titles = [
            c["title"] for c in spec["collections"]
        ]
        assert titles[:4] == [
            "New Arrivals", "On Sale", "In Stock",
            "Under $50",
        ]

    def test_niche_stacks_on_universal(self):
        spec = generate_smart_collections(niche="beauty")
        assert (
            len(spec["collections"])
            == len(_UNIVERSAL_COLLECTIONS)
            + len(_NICHE_COLLECTIONS["beauty"])
        )

    def test_unknown_niche_falls_back_to_general(self):
        spec = generate_smart_collections(niche="ufo_parts")
        # General has 0 niche-specific; total = universals
        assert (
            len(spec["collections"])
            == len(_UNIVERSAL_COLLECTIONS)
        )

    def test_every_niche_resolves(self):
        for niche in (
            "beauty", "fashion", "tech", "home", "food",
            "pets", "fitness", "jewelry", "outdoor",
            "baby", "general", "ufo_parts",
        ):
            spec = generate_smart_collections(niche=niche)
            assert spec["collections"]


class TestSpecShape:

    def test_full_shape_per_collection(self):
        for niche in _NICHE_COLLECTIONS:
            spec = generate_smart_collections(niche=niche)
            for c in spec["collections"]:
                assert c["title"], niche
                assert c["handle"], niche
                assert (
                    c["description_html"].startswith("<p>")
                ), niche
                assert c["sort_order"], niche
                assert c["rule_set"], niche
                assert "rules" in c["rule_set"], niche
                assert len(c["rule_set"]["rules"]) >= 1, (
                    niche, c["title"],
                )

    def test_rule_set_has_applied_disjunctively(self):
        spec = generate_smart_collections(niche="beauty")
        for c in spec["collections"]:
            assert "applied_disjunctively" in c["rule_set"]
            assert isinstance(
                c["rule_set"]["applied_disjunctively"], bool,
            )

    def test_rule_shape(self):
        """Each rule has column + relation + condition."""
        for niche in _NICHE_COLLECTIONS:
            spec = generate_smart_collections(niche=niche)
            for c in spec["collections"]:
                for r in c["rule_set"]["rules"]:
                    assert r["column"], niche
                    assert r["relation"], niche
                    assert "condition" in r, niche

    def test_handles_slug_cased(self):
        for niche in _NICHE_COLLECTIONS:
            spec = generate_smart_collections(niche=niche)
            for c in spec["collections"]:
                h = c["handle"]
                assert h == h.lower(), (niche, h)
                assert " " not in h, (niche, h)


class TestRuleEnumValues:

    def test_rule_columns_are_valid_shopify_enums(self):
        """All rule.column values must be from the
        Shopify-documented enum set."""
        valid_columns = {
            "TAG", "TITLE", "TYPE", "VENDOR",
            "VARIANT_PRICE", "VARIANT_COMPARE_AT_PRICE",
            "VARIANT_WEIGHT", "VARIANT_INVENTORY",
            "VARIANT_TITLE", "VARIANT_SKU",
            "IS_PRICE_REDUCED",
            "PRODUCT_CREATED_AT",
            "PRODUCT_METAFIELD_DEFINITION",
            "VARIANT_METAFIELD_DEFINITION",
            "PRODUCT_CATEGORY_ID",
        }
        for niche in _NICHE_COLLECTIONS:
            spec = generate_smart_collections(niche=niche)
            for c in spec["collections"]:
                for r in c["rule_set"]["rules"]:
                    assert r["column"] in valid_columns, (
                        niche, c["title"], r["column"],
                    )

    def test_rule_relations_are_valid_shopify_enums(self):
        valid_relations = {
            "EQUALS", "NOT_EQUALS",
            "GREATER_THAN", "LESS_THAN",
            "STARTS_WITH", "ENDS_WITH",
            "CONTAINS", "NOT_CONTAINS",
            "IS_SET", "IS_NOT_SET",
        }
        for niche in _NICHE_COLLECTIONS:
            spec = generate_smart_collections(niche=niche)
            for c in spec["collections"]:
                for r in c["rule_set"]["rules"]:
                    assert (
                        r["relation"] in valid_relations
                    ), (
                        niche, c["title"], r["relation"],
                    )

    def test_sort_orders_are_valid_shopify_enums(self):
        valid_sorts = {
            "ALPHA_ASC", "ALPHA_DESC",
            "BEST_SELLING",
            "CREATED", "CREATED_DESC",
            "MANUAL",
            "PRICE_ASC", "PRICE_DESC",
        }
        for niche in _NICHE_COLLECTIONS:
            spec = generate_smart_collections(niche=niche)
            for c in spec["collections"]:
                assert (
                    c["sort_order"] in valid_sorts
                ), (niche, c["title"], c["sort_order"])


class TestTagLibraryConsistency:
    """Tag-based rules reference family:value strings from
    `tag_library`. If those drift apart, smart collections
    auto-populate empty -- exactly the bug this test
    prevents."""

    def test_tag_rules_use_familyvalue_convention(self):
        """All TAG-based rule conditions should be either
        a bare tag (legacy / generic like 'sale') OR a
        family:value pair (the tag_library convention)."""
        for niche in _NICHE_COLLECTIONS:
            spec = generate_smart_collections(niche=niche)
            for c in spec["collections"]:
                for r in c["rule_set"]["rules"]:
                    if r["column"] != "TAG":
                        continue
                    cond = r["condition"]
                    # Either bare ("sale") OR family:value
                    if ":" in cond:
                        family, _, value = cond.partition(
                            ":",
                        )
                        assert family, (
                            niche, c["title"], cond,
                        )
                        assert value, (
                            niche, c["title"], cond,
                        )

    def test_niche_specific_tags_match_taxonomy(self):
        """Spot-check a few niche-specific tags against
        the actual tag_library taxonomy."""
        from engines.store_setup.tag_library import (
            get_niche_tags,
        )

        cases = {
            "beauty": "skin-type:sensitive",
            "fashion": "fit-type:plus",
            "tech": "feature:wireless",
            "jewelry": "metal:sterling-silver",
            "outdoor": "weather:waterproof",
        }
        for niche, expected_tag in cases.items():
            family, _, value = expected_tag.partition(":")
            taxonomy = get_niche_tags(niche)["families"]
            assert family in taxonomy, (niche, family)
            assert value in taxonomy[family], (
                niche, family, value,
            )


# ── _slug helper ─────────────────────────────────────────────


class TestSlug:

    def test_basic(self):
        assert _slug("On Sale") == "on-sale"
        assert _slug("Under $50") == "under-50"
        assert _slug("Sterling Silver") == "sterling-silver"

    def test_empty(self):
        assert _slug("") == "collection"
        assert _slug("   ") == "collection"


# ── Drop-in compatibility with collection_seeder applier ────


class TestApplierCompat:
    """Spec shape works with the existing
    `collection_seeder.apply_starter_collections`."""

    def test_applier_accepts_smart_specs(self):
        router = MagicMock()
        router.execute.return_value = SimpleNamespace(
            ok=True, data={}, error=None,
        )
        spec = generate_smart_collections(niche="beauty")
        with patch(
            "engines.store_setup.collection_seeder."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.collection_seeder."
            "record_writeback",
        ):
            out = apply_starter_collections(
                spec["collections"],
            )
        # Every smart collection applied
        assert (
            out["applied_count"]
            == len(spec["collections"])
        )
        # Confirm rule_set forwarded intact
        for call in router.execute.call_args_list:
            params = call.args[1]
            assert "rule_set" in params
            assert "rules" in params["rule_set"]
