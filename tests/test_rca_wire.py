"""Root-cause analyzer wire-up tests.

Audit batch 3 part 2: RootCauseAnalyzer was another orphan —
fully implemented but no public handle. These tests lock:
  * singleton access
  * MCP tool registered + dispatch shape
  * analyser handles ill-shaped input without crashing
"""
from __future__ import annotations

import unittest


class TestSingletonAccess(unittest.TestCase):
    def test_singleton_is_stable(self):
        from core.learning.root_cause_analyzer import (
            get_root_cause_analyzer,
            reset_rca_for_tests,
        )
        reset_rca_for_tests()
        a = get_root_cause_analyzer()
        b = get_root_cause_analyzer()
        self.assertIs(a, b)
        reset_rca_for_tests()


class TestMCPAnalyzeFailure(unittest.TestCase):
    def test_registered(self):
        from mcp_server.tools import build_default_registry

        reg = build_default_registry()
        specs = {s.name: s for s in reg.list_tools()}
        self.assertIn("analyze_failure", specs)
        spec = specs["analyze_failure"]
        self.assertFalse(spec.write)
        self.assertIn(
            "failed_episode",
            spec.input_schema.get("required", []),
        )

    def test_missing_episode_raises_tool_error(self):
        from mcp_server.tools import (
            _analyze_failure_handler, ToolError,
        )
        with self.assertRaises(ToolError):
            _analyze_failure_handler({})
        with self.assertRaises(ToolError):
            _analyze_failure_handler({
                "failed_episode": "not a dict",
            })

    def test_happy_path_returns_dict(self):
        from mcp_server.tools import (
            _analyze_failure_handler,
        )
        out = _analyze_failure_handler({
            "failed_episode": {
                "decision_type": "launch",
                "action": "publish_product",
                "context": {
                    "health_grade": "D",
                    "churn_pct": 45,
                    "competitor_active": True,
                },
            },
        })
        for k in (
            "root_causes", "contributing_factors",
            "lesson",
        ):
            self.assertIn(k, out)

    def test_non_dict_episode_handled(self):
        """Even if the episode is a dict but missing fields,
        the analyser returns a structured empty read instead
        of crashing."""
        from mcp_server.tools import (
            _analyze_failure_handler,
        )
        out = _analyze_failure_handler({
            "failed_episode": {},
        })
        self.assertIn("root_causes", out)


if __name__ == "__main__":
    unittest.main()
