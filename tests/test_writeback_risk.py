"""Tests for engines._writeback_risk."""
from __future__ import annotations

import ast
import textwrap

from engines._writeback_risk import (
    classify_writers,
    _classify,
)


class TestClassifier:

    def test_explicit_declaration_wins(self):
        src = textwrap.dedent('''
            _WRITEBACK_RISK = "destructive"
            # Even though the body looks additive,
            # the explicit declaration takes priority.
            def go():
                router.execute(Capability.SHOPIFY_TAG_CUSTOMER, ...)
        ''')
        tree = ast.parse(src)
        risk, declared, evidence = _classify(tree, src)
        assert risk == "destructive"
        assert declared is True

    def test_tag_customer_is_additive(self):
        src = textwrap.dedent('''
            from core.adapters.base import Capability
            def go():
                router.execute(
                    Capability.SHOPIFY_TAG_CUSTOMER,
                    {"id": cid, "tags": ["foo:bar"]},
                )
        ''')
        tree = ast.parse(src)
        risk, declared, _ = _classify(tree, src)
        assert risk == "additive"
        assert declared is False

    def test_update_product_with_only_tags_is_additive(self):
        # Tag merge counts as additive even though the
        # underlying capability is UPDATE_PRODUCT.
        src = textwrap.dedent('''
            from core.adapters.base import Capability
            def go():
                router.execute(
                    Capability.SHOPIFY_UPDATE_PRODUCT,
                    {"id": pid, "tags": merged},
                )
        ''')
        tree = ast.parse(src)
        risk, _, evidence = _classify(tree, src)
        assert risk == "additive"
        assert any("tag merge" in e for e in evidence)

    def test_update_product_with_status_is_modification(self):
        src = textwrap.dedent('''
            from core.adapters.base import Capability
            def go():
                router.execute(
                    Capability.SHOPIFY_UPDATE_PRODUCT,
                    {"id": pid, "status": "ARCHIVED"},
                )
        ''')
        tree = ast.parse(src)
        risk, _, evidence = _classify(tree, src)
        assert risk == "modification"
        assert any("status" in e for e in evidence)

    def test_update_variants_with_price_is_modification(self):
        src = textwrap.dedent('''
            from core.adapters.base import Capability
            def go():
                router.execute(
                    Capability.SHOPIFY_UPDATE_VARIANTS,
                    {"id": pid, "variants": [{"price": 9.99}]},
                )
        ''')
        tree = ast.parse(src)
        risk, _, _ = _classify(tree, src)
        assert risk == "modification"

    def test_create_product_is_additive(self):
        src = textwrap.dedent('''
            from core.adapters.base import Capability
            def go():
                router.execute(Capability.SHOPIFY_CREATE_PRODUCT, ...)
        ''')
        tree = ast.parse(src)
        risk, _, _ = _classify(tree, src)
        assert risk == "additive"

    def test_delete_product_is_destructive(self):
        src = textwrap.dedent('''
            from core.adapters.base import Capability
            def go():
                router.execute(Capability.SHOPIFY_DELETE_PRODUCT, ...)
        ''')
        tree = ast.parse(src)
        risk, _, _ = _classify(tree, src)
        assert risk == "destructive"

    def test_unknown_when_no_capability_found(self):
        src = textwrap.dedent('''
            def go():
                return 42
        ''')
        tree = ast.parse(src)
        risk, _, _ = _classify(tree, src)
        assert risk == "unknown"


class TestRealCodebase:

    def test_classify_all_writers(self):
        catalog = classify_writers("engines")
        # Every writer must classify -- no unknowns. If a new
        # writer doesn't fit a hint, the developer must add it
        # to one of the hint sets OR declare _WRITEBACK_RISK
        # explicitly.
        unknowns = catalog.by_risk.get("unknown", [])
        assert not unknowns, (
            f"Writers with unknown risk class: "
            f"{sorted({e.engine for e in unknowns})}. "
            f"Either add the engine's capability to a hint set "
            f"in engines/_writeback_risk.py OR add "
            f"`_WRITEBACK_RISK = 'additive'|'modification'|"
            f"'destructive'` to the writer module."
        )

    def test_most_writers_are_additive(self):
        """Architectural invariant: the bulk of Phase 7
        writebacks should be safe-by-default (additive). If
        the modification count balloons, that's a signal we're
        building too many high-risk wireups."""
        catalog = classify_writers("engines")
        additive = catalog.count("additive")
        modification = catalog.count("modification")
        destructive = catalog.count("destructive")
        # Today: 45 additive, 6 modification, 0 destructive.
        # Architectural floor: additive must be at least 5x mod.
        assert additive > 5 * modification, (
            f"Architectural invariant violated: "
            f"additive={additive}, modification={modification}. "
            f"Additive should dominate."
        )
        # Hard cap on destructive -- needs explicit operator
        # opt-in for each. If this grows past 3, the codebase
        # is silently introducing more risk.
        assert destructive <= 3, (
            f"Too many destructive writers: {destructive}. "
            f"These bypass the standard approval queue."
        )

    def test_known_modification_writers(self):
        """The KNOWN modification writers must stay classified
        as such. Catches regressions where someone accidentally
        widens an applier from tag-only to status-changing."""
        catalog = classify_writers("engines")
        mod_engines = {e.engine for e in catalog.by_risk.get("modification", [])}
        expected_mods = {
            "dynamic_pricing",      # price changes
            "pricing",              # price changes
            "product_lifecycle",    # archive status
            "product_optimization", # variants/status
        }
        missing = expected_mods - mod_engines
        assert not missing, (
            f"Known-modification engines no longer classified "
            f"as modification: {sorted(missing)}. They may have "
            f"been downgraded -- verify the change is intentional."
        )
