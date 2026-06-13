"""Tests for engines._tag_catalog."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from engines._tag_catalog import catalog_tags, _extract_tag_literals
import ast


class TestExtraction:

    def test_extracts_module_level_constant(self):
        src = textwrap.dedent('''
            _RISK_TAG = "risk:high"
            def go():
                pass
        ''')
        tree = ast.parse(src)
        tags = _extract_tag_literals(tree)
        assert "risk:high" in tags

    def test_extracts_fstring_prefix_as_wildcard(self):
        src = textwrap.dedent('''
            def go(period):
                return f"cohort:{period}"
        ''')
        tree = ast.parse(src)
        tags = _extract_tag_literals(tree)
        assert "cohort:*" in tags

    def test_excludes_adapter_error_prefixes(self):
        src = textwrap.dedent('''
            def go(exc):
                return f"adapter_failed: {exc}"
        ''')
        tree = ast.parse(src)
        tags = _extract_tag_literals(tree)
        assert all(not t.startswith("adapter_failed") for t in tags)

    def test_extracts_inlined_list_literal(self):
        src = textwrap.dedent('''
            def go():
                router.execute(cap, {"id": "x", "tags": ["ces:high_effort"]})
        ''')
        tree = ast.parse(src)
        tags = _extract_tag_literals(tree)
        assert "ces:high_effort" in tags

    def test_skips_non_tag_strings(self):
        src = textwrap.dedent('''
            DOC = "this:has a colon but isnt a tag"
            def go():
                return "https://example.com"
        ''')
        tree = ast.parse(src)
        tags = _extract_tag_literals(tree)
        assert not tags

    def test_extracts_tag_prefix_constant(self):
        # customer_segmentation-style: _TAG_PREFIX = "ns-"
        src = textwrap.dedent('''
            _TAG_PREFIX = "shopai-segment-"
        ''')
        tree = ast.parse(src)
        tags = _extract_tag_literals(tree)
        assert "shopai-segment-*" in tags

    def test_skips_capitalized_fstring_prefixes(self):
        # f"Bundle: foo" in a docstring/log shouldn't be a tag
        src = textwrap.dedent('''
            def go(x):
                return f"Bundle: {x}"
        ''')
        tree = ast.parse(src)
        tags = _extract_tag_literals(tree)
        assert not tags


class TestCatalog:

    def test_scans_real_engines_dir(self):
        catalog = catalog_tags("engines")
        # We have 24+ tag_applier.py files at this point in the
        # session. The exact count grows over time but the
        # invariant is: >0 engines, every entry has a target.
        assert catalog.engines_scanned > 0
        assert catalog.total_tags > 0
        for entry in catalog.entries:
            assert entry.engine
            assert entry.tag
            assert entry.target in {
                "product", "customer", "order", "unknown",
            }

    def test_target_classification(self):
        catalog = catalog_tags("engines")
        # At least one product-tag and one customer-tag should
        # exist (we have both kinds in Phase 7).
        assert catalog.by_target.get("product"), \
            "Expected at least one product-tag engine"
        assert catalog.by_target.get("customer"), \
            "Expected at least one customer-tag engine"

    def test_missing_dir_returns_empty_catalog(self):
        catalog = catalog_tags("does-not-exist-xyz")
        assert catalog.engines_scanned == 0
        assert catalog.total_tags == 0
        assert catalog.entries == []

    def test_namespace_grouping(self):
        catalog = catalog_tags("engines")
        # Every namespace key matches a tag's prefix. Tags use one
        # of two conventions: ``namespace:value`` (most engines)
        # OR ``namespace-value`` (customer_segmentation,
        # bundle's shopai-X-Y-{slug} style).
        for ns, entries in catalog.by_namespace.items():
            for e in entries:
                assert (
                    e.tag.startswith(f"{ns}:")
                    or e.tag.startswith(f"{ns}-")
                )


class TestCIInvariants:
    """CI guardrail: tag-writing wireups must be discoverable.

    A wired engine that uses SHOPIFY_UPDATE_PRODUCT,
    SHOPIFY_TAG_CUSTOMER, SHOPIFY_TAG_ORDER, or
    SHOPIFY_CREATE_PRODUCT in its applier MUST appear in the
    catalog. Otherwise the operator surfaces silently miss it
    and operators can't discover the namespace it writes.
    """

    def _tag_writing_engines(self) -> set[str]:
        """Engines whose *_applier.py actually writes a tags field
        to Shopify (not just any UPDATE_PRODUCT call -- many use
        UPDATE_PRODUCT for status/price changes without tags).

        Heuristic: applier mentions a tag-write capability AND
        the source contains ``"tags":`` or ``tags=[`` (the
        actual write-site markers).
        """
        import re
        from pathlib import Path

        cap_pattern = re.compile(
            r"SHOPIFY_(UPDATE_PRODUCT|CREATE_PRODUCT|TAG_CUSTOMER|TAG_ORDER)"
        )
        # The applier must construct a tags payload to count as
        # a tag-writer. Otherwise UPDATE_PRODUCT is used for
        # status changes, price changes, etc. and there's no
        # tag to catalog.
        tag_marker = re.compile(r'"tags"\s*:|tags\s*=\s*\[')
        out: set[str] = set()
        for engine_dir in Path("engines").iterdir():
            if not engine_dir.is_dir():
                continue
            for applier in engine_dir.glob("*_applier.py"):
                try:
                    source = applier.read_text(encoding="utf-8")
                except OSError:
                    continue
                if cap_pattern.search(source) and tag_marker.search(source):
                    out.add(engine_dir.name)
                    break
        return out

    def test_every_tag_writing_engine_in_catalog(self):
        """Catalog catches every applier with a Shopify tag-write
        capability. Regressions where a new applier uses an
        undetectable pattern break this test loudly."""
        catalog = catalog_tags("engines")
        catalog_engines = {e.engine for e in catalog.entries}
        tag_writers = self._tag_writing_engines()

        missing = tag_writers - catalog_engines
        # Engines we KNOW use other constructs (not tag literals
        # we can statically detect). They're tag-writing but the
        # tag value comes from dynamic input the catalog can't see.
        # Tag-management is a prime example -- it writes whatever
        # tags the upstream engine emits, not a fixed namespace.
        known_dynamic = {
            "tag_management",      # caller-supplied tags
        }
        unexpected_missing = missing - known_dynamic
        assert not unexpected_missing, (
            f"These engines write Shopify tags but the catalog "
            f"doesn't catch any of their tag literals: "
            f"{sorted(unexpected_missing)}. Either add a detection "
            f"pattern in engines/_tag_catalog.py or add the engine "
            f"name to the known_dynamic allow-list in this test."
        )
