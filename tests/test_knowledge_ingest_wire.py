"""Knowledge-ingest CLI + MCP wire tests (audit batch 3).

The module existed as a fully implemented orphan. This batch
gives it owner-facing handles so brand docs / changelogs /
supplier FAQs can flow into the knowledge base without
editing code.
"""
from __future__ import annotations

import tempfile
import unittest


class TestMCPIngestKnowledge(unittest.TestCase):
    def test_tool_registered_write_gated(self):
        from mcp_server.tools import build_default_registry

        reg = build_default_registry()
        specs = {s.name: s for s in reg.list_tools()}
        self.assertIn("ingest_knowledge", specs)
        spec = specs["ingest_knowledge"]
        self.assertTrue(
            spec.write,
            "ingest writes to KB — must be gated",
        )

    def test_handler_requires_source(self):
        from mcp_server.tools import (
            _ingest_knowledge_handler, ToolError,
        )
        with self.assertRaises(ToolError):
            _ingest_knowledge_handler({})

    def test_handler_text_path_returns_dict(self):
        from mcp_server.tools import (
            _ingest_knowledge_handler,
        )
        out = _ingest_knowledge_handler({
            "text": (
                "# Brand\n"
                "- Tagline: Quality Delivered\n"
                "- Founded: 2024\n"
                "- Headquarters: Ulaanbaatar\n"
            ),
        })
        for k in (
            "source", "subject", "facts_written",
            "facts_skipped", "errors",
        ):
            self.assertIn(k, out)
        # Subject pulled from first heading
        self.assertEqual(out["subject"].lower(), "brand")

    def test_handler_file_path(self):
        from mcp_server.tools import (
            _ingest_knowledge_handler,
        )
        tmp = tempfile.NamedTemporaryFile(
            "w", suffix=".md", delete=False,
        )
        try:
            tmp.write(
                "# Policies\n"
                "- Returns: 30-day window\n"
                "- Shipping: Free over $50\n"
            )
            tmp.close()
            out = _ingest_knowledge_handler({
                "file": tmp.name,
            })
            self.assertEqual(out["subject"].lower(), "policies")
        finally:
            import os
            os.unlink(tmp.name)

    def test_handler_short_text_recorded_as_error(self):
        """Empty / too-short text → structured error response,
        not an exception."""
        from mcp_server.tools import (
            _ingest_knowledge_handler,
        )
        out = _ingest_knowledge_handler({"text": "hi"})
        self.assertIn("errors", out)
        self.assertTrue(out["errors"])

    def test_subject_override_honoured(self):
        from mcp_server.tools import (
            _ingest_knowledge_handler,
        )
        out = _ingest_knowledge_handler({
            "text": (
                "- one: alpha\n"
                "- two: bravo\n"
                "- three: charlie\n"
            ),
            "subject": "custom_subject",
        })
        self.assertEqual(out["subject"], "custom_subject")


if __name__ == "__main__":
    unittest.main()
