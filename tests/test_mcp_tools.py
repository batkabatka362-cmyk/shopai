"""Tests for mcp_server.tools (Wave B-2)."""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from mcp_server.tools import (
    ToolCall,
    ToolError,
    ToolRegistry,
    ToolResult,
    ToolSpec,
    build_default_registry,
)


class TestRegistry(unittest.TestCase):
    def test_register_and_list(self):
        reg = ToolRegistry()
        reg.register(ToolSpec(
            name="x",
            description="d",
            input_schema={},
            handler=lambda args: {"ok": True},
        ))
        self.assertEqual(len(reg.list_tools()), 1)

    def test_duplicate_register_rejected(self):
        reg = ToolRegistry()
        spec = ToolSpec(
            name="x",
            description="d",
            input_schema={},
            handler=lambda args: {},
        )
        reg.register(spec)
        with self.assertRaises(ValueError):
            reg.register(spec)

    def test_blank_name_rejected(self):
        reg = ToolRegistry()
        with self.assertRaises(ValueError):
            reg.register(ToolSpec(
                name="", description="d",
                input_schema={},
                handler=lambda a: {},
            ))


class TestCall(unittest.TestCase):
    def test_unknown_tool(self):
        reg = ToolRegistry()
        r = reg.call(ToolCall(tool="nope"))
        self.assertFalse(r.ok)
        self.assertIn("unknown tool", r.error)

    def test_happy_call(self):
        reg = ToolRegistry()
        reg.register(ToolSpec(
            name="echo",
            description="d",
            input_schema={},
            handler=lambda a: {"got": a.get("v")},
        ))
        r = reg.call(ToolCall(
            tool="echo",
            arguments={"v": 42},
        ))
        self.assertTrue(r.ok)
        self.assertEqual(r.content, {"got": 42})
        self.assertGreaterEqual(r.latency_ms, 0)

    def test_tool_error_captured(self):
        reg = ToolRegistry()

        def boom(args):
            raise ToolError("bad input")

        reg.register(ToolSpec(
            name="fail",
            description="d",
            input_schema={},
            handler=boom,
        ))
        r = reg.call(ToolCall(tool="fail"))
        self.assertFalse(r.ok)
        self.assertEqual(r.error, "bad input")

    def test_unexpected_exception_captured(self):
        reg = ToolRegistry()

        def crash(args):
            raise RuntimeError("db down")

        reg.register(ToolSpec(
            name="crash",
            description="d",
            input_schema={},
            handler=crash,
        ))
        r = reg.call(ToolCall(tool="crash"))
        self.assertFalse(r.ok)
        self.assertIn("db down", r.error)

    def test_non_toolcall_type_raises(self):
        reg = ToolRegistry()
        with self.assertRaises(TypeError):
            reg.call({"tool": "x"})

    def test_stats_counts(self):
        reg = ToolRegistry()
        reg.register(ToolSpec(
            name="ok",
            description="d",
            input_schema={},
            handler=lambda a: {},
        ))
        reg.call(ToolCall(tool="ok"))
        reg.call(ToolCall(tool="nope"))
        s = reg.stats()
        self.assertEqual(s["total_calls"], 1)
        self.assertEqual(s["total_errors"], 0)


class TestToolResult(unittest.TestCase):
    def test_to_mcp_success(self):
        r = ToolResult(
            tool="x", ok=True,
            content={"a": 1},
        )
        out = r.to_mcp()
        self.assertFalse(out["isError"])
        self.assertIn("a", out["content"][0]["text"])

    def test_to_mcp_string_content(self):
        r = ToolResult(
            tool="x", ok=True,
            content="plain text",
        )
        out = r.to_mcp()
        self.assertEqual(
            out["content"][0]["text"], "plain text",
        )

    def test_to_mcp_error(self):
        r = ToolResult(
            tool="x", ok=False, error="boom",
        )
        out = r.to_mcp()
        self.assertTrue(out["isError"])
        self.assertIn("boom", out["content"][0]["text"])


class TestDefaultRegistry(unittest.TestCase):
    def test_expected_tools_present(self):
        reg = build_default_registry()
        names = {t.name for t in reg.list_tools()}
        for expected in (
            "brain_snapshot",
            "risk_status",
            "list_rules",
            "explain_decision",
            "agentic_channels",
            "landed_cost_calc",
            "launch_simulate",
            "emergency_halt",
            "emergency_resume",
        ):
            self.assertIn(expected, names)

    def test_write_tools_marked(self):
        reg = build_default_registry()
        tools = {t.name: t for t in reg.list_tools()}
        self.assertTrue(tools["emergency_halt"].write)
        self.assertTrue(tools["emergency_resume"].write)
        self.assertFalse(tools["brain_snapshot"].write)

    def test_landed_cost_handler_callable(self):
        reg = build_default_registry()
        r = reg.call(ToolCall(
            tool="landed_cost_calc",
            arguments={
                "fob_usd": 10, "destination": "US",
                "origin": "CN", "shipping_usd": 3,
            },
        ))
        self.assertTrue(r.ok)
        self.assertIn("total_usd", r.content)

    def test_landed_cost_invalid_args(self):
        reg = build_default_registry()
        r = reg.call(ToolCall(
            tool="landed_cost_calc",
            arguments={
                "fob_usd": "not a number",
                "destination": "US",
            },
        ))
        self.assertFalse(r.ok)
        self.assertIn("invalid args", r.error)

    def test_launch_simulate_happy(self):
        reg = build_default_registry()
        r = reg.call(ToolCall(
            tool="launch_simulate",
            arguments={
                "cost": 5, "price": 30,
                "daily_budget_usd": 20, "days": 3,
            },
        ))
        self.assertTrue(r.ok)
        self.assertIn("verdict", r.content)

    def test_explain_decision_requires_id(self):
        reg = build_default_registry()
        r = reg.call(ToolCall(
            tool="explain_decision",
            arguments={},
        ))
        self.assertFalse(r.ok)

    def test_list_rules_runs(self):
        reg = build_default_registry()
        r = reg.call(ToolCall(
            tool="list_rules",
            arguments={"limit": 5},
        ))
        self.assertTrue(r.ok)
        self.assertIsInstance(r.content, list)


class TestDicts(unittest.TestCase):
    def test_call_dict(self):
        c = ToolCall(tool="x", arguments={"a": 1})
        self.assertEqual(c.as_dict()["tool"], "x")

    def test_result_dict(self):
        r = ToolResult(tool="x", ok=True, content=None)
        self.assertIn("latency_ms", r.as_dict())

    def test_spec_dict(self):
        s = ToolSpec(
            name="x", description="d",
            input_schema={}, handler=lambda a: {},
        )
        self.assertIn("write", s.as_dict())


if __name__ == "__main__":
    unittest.main()
