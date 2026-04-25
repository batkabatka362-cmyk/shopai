"""External knowledge ingestion — parser + writer tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from core.memory import knowledge_ingest as ki


class TestSlug(unittest.TestCase):
    def test_strips_punctuation(self) -> None:
        self.assertEqual(ki._slug("Shopify Admin API!"),
                         "shopify_admin_api")

    def test_empty_input_returns_doc(self) -> None:
        self.assertEqual(ki._slug(""), "doc")


class TestCoerce(unittest.TestCase):
    def test_coerce_bool(self) -> None:
        self.assertIs(ki._coerce("true"), True)
        self.assertIs(ki._coerce("NO"), False)

    def test_coerce_int(self) -> None:
        self.assertEqual(ki._coerce("42"), 42)

    def test_coerce_float(self) -> None:
        self.assertEqual(ki._coerce("1.5"), 1.5)

    def test_keeps_string(self) -> None:
        self.assertEqual(ki._coerce("hello world"), "hello world")


class TestStripHtml(unittest.TestCase):
    def test_strips_tags_and_script(self) -> None:
        html = "<html><script>alert(1)</script><body><b>X</b>: 5</body></html>"
        out = ki._strip_html(html)
        self.assertNotIn("<", out)
        self.assertNotIn("alert", out)
        self.assertIn("X", out)

    def test_strips_entities(self) -> None:
        self.assertNotIn(
            "&amp;",
            ki._strip_html("A &amp; B"),
        )


class TestFactExtraction(unittest.TestCase):
    def test_bullet_facts(self) -> None:
        md = (
            "# Shopify\n"
            "- **max_metafield_bytes**: 5242880\n"
            "- **rate_limit_calls_per_second** = 2\n"
            "- Normal text without colon\n"
        )
        facts = ki._extract_facts(md, "shopify")
        preds = [f[1] for f in facts]
        self.assertIn("max_metafield_bytes", preds)
        self.assertIn("rate_limit_calls_per_second", preds)

    def test_definition_facts(self) -> None:
        text = (
            "# Doc\n"
            "launch_kill_threshold: 1.5\n"
            "scale_threshold: 2.0\n"
        )
        facts = ki._extract_facts(text, "doc")
        self.assertEqual(len(facts), 2)
        objs = {f[1]: f[2] for f in facts}
        self.assertEqual(objs["launch_kill_threshold"], 1.5)
        self.assertEqual(objs["scale_threshold"], 2.0)

    def test_dedupes_by_predicate(self) -> None:
        md = (
            "- threshold: 1.0\n"
            "- **threshold**: 2.0\n"   # duplicate predicate → keep first
        )
        facts = ki._extract_facts(md, "doc")
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0][2], 1.0)


class _FakeKB:
    """Minimal stand-in — Mock's `assert_*` safety prevents us from
    using its spec-less attribute on methods named ``assert_fact``."""
    def __init__(self):
        self.calls = []
    def assert_fact(self, subject, predicate, obj, source=""):
        self.calls.append((subject, predicate, obj, source))
        return None


class TestIngestText(unittest.TestCase):
    def test_writes_to_kb(self) -> None:
        kb = _FakeKB()
        with patch("core.memory.knowledge_base.knowledge_base",
                   return_value=kb):
            result = ki.ingest_text(
                "# Shopify\n- **rate_limit**: 2\n",
                source="unit_test",
            )
        self.assertEqual(result.facts_written, 1)
        self.assertEqual(len(kb.calls), 1)
        subj, pred, obj, src = kb.calls[0]
        self.assertEqual(subj, "shopify")
        self.assertEqual(pred, "rate_limit")
        self.assertEqual(obj, 2)
        self.assertEqual(src, "unit_test")

    def test_empty_text_returns_error(self) -> None:
        r = ki.ingest_text("", source="x")
        self.assertIn("too short", r.errors[0])

    def test_uses_supplied_subject(self) -> None:
        kb = _FakeKB()
        with patch("core.memory.knowledge_base.knowledge_base",
                   return_value=kb):
            r = ki.ingest_text(
                "- foo: bar\n",
                source="x",
                subject="my_subject",
            )
        self.assertEqual(r.subject, "my_subject")


class TestIngestFile(unittest.TestCase):
    def test_reads_local_markdown(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write("# Shopify\n- **rate_limit**: 2\n")
            tmp = f.name
        kb = _FakeKB()
        try:
            with patch("core.memory.knowledge_base.knowledge_base",
                       return_value=kb):
                r = ki.ingest_file(tmp)
            self.assertEqual(r.facts_written, 1)
        finally:
            Path(tmp).unlink()

    def test_missing_file_returns_error(self) -> None:
        r = ki.ingest_file("/nonexistent/path.md")
        self.assertIn("not found", r.errors[0])


class TestIngestUrl(unittest.TestCase):
    def test_invalid_scheme_rejected(self) -> None:
        r = ki.ingest_url("ftp://x.com")
        self.assertIn("invalid URL", r.errors[0])

    def test_network_failure_returns_error(self) -> None:
        with patch.object(ki, "_fetch_http", return_value=None):
            r = ki.ingest_url("https://x.com")
        self.assertIn("fetch failed", r.errors[0])


if __name__ == "__main__":
    unittest.main()
