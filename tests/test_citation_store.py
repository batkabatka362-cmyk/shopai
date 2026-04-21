"""Tests for the GEO citation store + auto-injection wire."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from execution.seo import citation_store as cs


def _write_niche(
    base: Path, niche: str, rows: list[dict],
) -> None:
    base.mkdir(parents=True, exist_ok=True)
    (base / f"{niche}.json").write_text(
        json.dumps(rows),
    )


def _citation(**kw):
    defaults = dict(
        claim="Slow feeders cut bloat by 40%.",
        quote="Dogs that eat slowly digest better.",
        source_name="Dr. Elena Martinez",
        source_type="expert",
        citation="AVMA Journal 2024",
    )
    defaults.update(kw)
    return defaults


class TestSanitise(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(cs._sanitise_niche("Pet"), "pet")

    def test_spaces_and_caps(self):
        self.assertEqual(
            cs._sanitise_niche("Pet Supplies"),
            "pet-supplies",
        )

    def test_non_alnum(self):
        self.assertEqual(
            cs._sanitise_niche("Pet_Food/US!"),
            "pet-food-us",
        )

    def test_empty_falls_back_to_default(self):
        self.assertEqual(
            cs._sanitise_niche(""), "default",
        )


class TestRead(unittest.TestCase):
    def setUp(self):
        cs.reset_cache_for_tests()

    def test_missing_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(
                cs._read_citations(
                    "unknown",
                    base=Path(td),
                    now_fn=lambda: 1.0,
                ),
                [],
            )

    def test_malformed_json_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            base.mkdir(exist_ok=True)
            (base / "pet.json").write_text("not json")
            self.assertEqual(
                cs._read_citations(
                    "pet",
                    base=base,
                    now_fn=lambda: 1.0,
                ),
                [],
            )

    def test_non_list_root_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            base.mkdir(exist_ok=True)
            (base / "pet.json").write_text(
                json.dumps({"not": "a list"}),
            )
            self.assertEqual(
                cs._read_citations(
                    "pet",
                    base=base,
                    now_fn=lambda: 1.0,
                ),
                [],
            )

    def test_skips_rows_missing_required(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            _write_niche(base, "pet", [
                _citation(),
                {"claim": "", "quote": "q"},  # skip
                {"quote": "only quote"},  # skip
                "not a dict",  # skip
                _citation(claim="Second real"),
            ])
            cs.reset_cache_for_tests()
            cites = cs._read_citations(
                "pet",
                base=base,
                now_fn=lambda: 1.0,
            )
            self.assertEqual(len(cites), 2)

    def test_valid_rows_loaded(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            _write_niche(base, "pet", [
                _citation(),
                _citation(claim="Second"),
            ])
            cs.reset_cache_for_tests()
            cites = cs._read_citations(
                "pet",
                base=base,
                now_fn=lambda: 1.0,
            )
            self.assertEqual(len(cites), 2)

    def test_niche_sanitisation_lands_same_file(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            _write_niche(base, "pet-supplies", [
                _citation(),
            ])
            cs.reset_cache_for_tests()
            # All variants resolve to pet-supplies.json
            for alias in (
                "pet supplies",
                "Pet Supplies",
                "pet_supplies",
                "PET-SUPPLIES",
            ):
                cites = cs._read_citations(
                    alias, base=base,
                    now_fn=lambda: 1.0,
                )
                self.assertEqual(len(cites), 1)


class TestResolveCitations(unittest.TestCase):
    def setUp(self):
        cs.reset_cache_for_tests()

    def test_explicit_citations_untouched(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            _write_niche(base, "pet", [_citation()])
            product = {
                "niche": "pet",
                "citations": [
                    _citation(
                        claim="Explicit wins",
                    ),
                ],
            }
            cs.reset_cache_for_tests()
            cites = cs.resolve_citations_for(
                product, base=base,
            )
            self.assertEqual(len(cites), 1)
            self.assertEqual(
                cites[0]["claim"], "Explicit wins",
            )

    def test_falls_back_to_niche(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            _write_niche(base, "pet", [
                _citation(source_name="Vet 1"),
                _citation(source_name="Vet 2"),
            ])
            cs.reset_cache_for_tests()
            cites = cs.resolve_citations_for(
                {"niche": "pet"}, base=base,
            )
            self.assertEqual(len(cites), 2)

    def test_falls_back_to_category(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            _write_niche(base, "beauty", [_citation()])
            cs.reset_cache_for_tests()
            cites = cs.resolve_citations_for(
                {"category": "beauty"}, base=base,
            )
            self.assertEqual(len(cites), 1)

    def test_falls_back_to_default(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            _write_niche(base, "default", [_citation()])
            cs.reset_cache_for_tests()
            cites = cs.resolve_citations_for(
                {"niche": "unknown-niche"}, base=base,
            )
            self.assertEqual(len(cites), 1)

    def test_empty_when_nothing_curated(self):
        with tempfile.TemporaryDirectory() as td:
            cs.reset_cache_for_tests()
            cites = cs.resolve_citations_for(
                {"niche": "x"}, base=Path(td),
            )
            self.assertEqual(cites, [])


class TestInjectCitations(unittest.TestCase):
    def setUp(self):
        cs.reset_cache_for_tests()

    def test_adds_citations_when_absent(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            _write_niche(base, "pet", [_citation()])
            cs.reset_cache_for_tests()
            out = cs.inject_citations(
                {"niche": "pet", "title": "X"},
                base=base,
            )
            self.assertIn("citations", out)
            self.assertEqual(len(out["citations"]), 1)

    def test_does_not_overwrite_explicit(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            _write_niche(base, "pet", [_citation()])
            cs.reset_cache_for_tests()
            orig = {
                "niche": "pet",
                "citations": [
                    _citation(claim="mine"),
                ],
            }
            out = cs.inject_citations(orig, base=base)
            self.assertEqual(len(out["citations"]), 1)
            self.assertEqual(
                out["citations"][0]["claim"], "mine",
            )

    def test_returns_shallow_copy(self):
        with tempfile.TemporaryDirectory() as td:
            orig = {"niche": "x"}
            out = cs.inject_citations(
                orig, base=Path(td),
            )
            self.assertIsNot(out, orig)


class TestAvailableNiches(unittest.TestCase):
    def test_lists_files(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            _write_niche(base, "pet", [_citation()])
            _write_niche(base, "beauty", [_citation()])
            niches = cs.available_niches(base=base)
            self.assertEqual(niches, ["beauty", "pet"])

    def test_missing_dir(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "does-not-exist"
            self.assertEqual(
                cs.available_niches(base=base), [],
            )


class TestContentGeneratorWire(unittest.TestCase):
    """End-to-end: ContentGenerator picks up niche citations
    when no explicit citations are on the product dict."""

    def test_niche_citations_auto_injected(self):
        from core.intelligence.content_generator import (
            ContentGenerator,
        )
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            _write_niche(base, "pet", [
                _citation(claim="Niche claim one"),
            ])
            cs.reset_cache_for_tests()
            with patch(
                "execution.seo.citation_store._DEFAULT_DIR",
                base,
            ):
                gen = ContentGenerator()
                out = gen.product_description(
                    {
                        "name": "Pet Bowl",
                        "price": 29.99,
                        "niche": "pet",
                    },
                    use_geo_sandwich=True,
                )
        self.assertIn("geo_sandwiches", out)
        self.assertEqual(
            len(out["geo_sandwiches"]), 1,
        )
        self.assertIn(
            "Niche claim one", out["body_html"],
        )

    def test_explicit_citations_still_win(self):
        from core.intelligence.content_generator import (
            ContentGenerator,
        )
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            _write_niche(base, "pet", [
                _citation(claim="Niche claim"),
            ])
            cs.reset_cache_for_tests()
            with patch(
                "execution.seo.citation_store._DEFAULT_DIR",
                base,
            ):
                gen = ContentGenerator()
                out = gen.product_description(
                    {
                        "name": "Pet Bowl",
                        "price": 29.99,
                        "niche": "pet",
                        "citations": [
                            _citation(
                                claim="Explicit wins",
                            ),
                        ],
                    },
                    use_geo_sandwich=True,
                )
        self.assertEqual(
            len(out["geo_sandwiches"]), 1,
        )
        self.assertIn(
            "Explicit wins", out["body_html"],
        )


class TestMcpTool(unittest.TestCase):
    def test_registered(self):
        from mcp_server.tools import build_default_registry
        reg = build_default_registry()
        names = {s.name for s in reg.list_tools()}
        self.assertIn("citations_show", names)

    def test_returns_structure(self):
        from mcp_server.tools import (
            ToolCall, build_default_registry,
        )
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            _write_niche(base, "pet", [_citation()])
            cs.reset_cache_for_tests()
            with patch(
                "execution.seo.citation_store._DEFAULT_DIR",
                base,
            ):
                reg = build_default_registry()
                res = reg.call(ToolCall(
                    tool="citations_show",
                    arguments={"niche": "pet"},
                ))
        self.assertTrue(res.ok)
        self.assertEqual(res.content["niche"], "pet")
        self.assertEqual(res.content["count"], 1)
        self.assertIn(
            "available_niches", res.content,
        )


if __name__ == "__main__":
    unittest.main()
