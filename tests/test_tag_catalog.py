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
        # Every namespace key matches a tag's prefix
        for ns, entries in catalog.by_namespace.items():
            for e in entries:
                assert e.tag.startswith(f"{ns}:")
