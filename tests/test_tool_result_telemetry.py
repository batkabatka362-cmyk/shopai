"""ToolResult telemetry extension tests (quality audit item #6).

Pre-audit: ``ToolResult`` had 5 fields (tool, ok, content,
error, latency_ms); ``AdapterResult`` had 10+ (adding
cost_usd, tokens_in, tokens_out, model, adapter, …). When
an MCP tool called an adapter, the vendor's cost +
token accounting was silently dropped at the boundary so
the owner couldn't budget MCP traffic.

This test locks in the extended contract:
  * ToolResult carries the same telemetry shape
  * from_adapter_result() factory preserves everything
  * Backward compat: existing handlers that don't set the
    new fields still serialise cleanly (zeros).
"""
from __future__ import annotations

import unittest
from dataclasses import dataclass

from mcp_server.tools import ToolResult


@dataclass
class _FakeAdapterResult:
    """Minimal shape that mirrors core.adapters.base.AdapterResult
    without importing the full module (keeps the test offline)."""
    ok: bool
    adapter: str = ""
    capability: str = ""
    data: object = None
    error: object = None
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    model: str = ""


class TestExtendedFields(unittest.TestCase):
    def test_defaults_backward_compat(self):
        r = ToolResult(tool="x", ok=True)
        d = r.as_dict()
        self.assertEqual(d["cost_usd"], 0.0)
        self.assertEqual(d["tokens_in"], 0)
        self.assertEqual(d["tokens_out"], 0)
        self.assertEqual(d["model"], "")
        self.assertEqual(d["adapter"], "")

    def test_direct_construction_preserves_telemetry(self):
        r = ToolResult(
            tool="chat",
            ok=True,
            content={"reply": "hi"},
            latency_ms=124.5,
            cost_usd=0.00042,
            tokens_in=50,
            tokens_out=8,
            model="claude-3-haiku",
            adapter="anthropic",
        )
        d = r.as_dict()
        self.assertEqual(d["cost_usd"], 0.00042)
        self.assertEqual(d["tokens_in"], 50)
        self.assertEqual(d["tokens_out"], 8)
        self.assertEqual(d["model"], "claude-3-haiku")
        self.assertEqual(d["adapter"], "anthropic")

    def test_as_dict_rounds_cost_to_6_places(self):
        r = ToolResult(
            tool="x", ok=True,
            cost_usd=0.123456789,
        )
        self.assertEqual(
            r.as_dict()["cost_usd"], 0.123457,
        )


class TestFromAdapterResultFactory(unittest.TestCase):
    def test_copies_all_telemetry(self):
        ar = _FakeAdapterResult(
            ok=True,
            adapter="gemini",
            data={"answer": "x"},
            latency_ms=250.0,
            cost_usd=0.003,
            tokens_in=100,
            tokens_out=20,
            model="gemini-1.5-flash",
        )
        t = ToolResult.from_adapter_result(
            tool="ask_model", adapter_result=ar,
        )
        self.assertTrue(t.ok)
        self.assertEqual(t.tool, "ask_model")
        self.assertEqual(t.content, {"answer": "x"})
        self.assertAlmostEqual(t.cost_usd, 0.003)
        self.assertEqual(t.tokens_in, 100)
        self.assertEqual(t.tokens_out, 20)
        self.assertEqual(t.model, "gemini-1.5-flash")
        self.assertEqual(t.adapter, "gemini")
        self.assertEqual(t.latency_ms, 250.0)

    def test_failure_copies_error(self):
        class _Err:
            def __str__(self) -> str:
                return "rate limit"

        ar = _FakeAdapterResult(
            ok=False, adapter="groq", error=_Err(),
        )
        t = ToolResult.from_adapter_result(
            tool="chat", adapter_result=ar,
        )
        self.assertFalse(t.ok)
        self.assertIn("rate limit", t.error)
        self.assertEqual(t.adapter, "groq")

    def test_handles_missing_attributes(self):
        """Minimal objects (e.g. MagicMock(ok=True)) still
        produce a sane ToolResult with zero telemetry."""
        class _Bare:
            ok = True
        t = ToolResult.from_adapter_result(
            tool="x", adapter_result=_Bare(),
        )
        self.assertTrue(t.ok)
        self.assertEqual(t.cost_usd, 0.0)
        self.assertEqual(t.tokens_in, 0)
        self.assertEqual(t.model, "")
        self.assertEqual(t.adapter, "")

    def test_none_values_coerce_to_zero(self):
        ar = _FakeAdapterResult(
            ok=True,
            latency_ms=None,  # type: ignore[arg-type]
            cost_usd=None,  # type: ignore[arg-type]
            tokens_in=None,  # type: ignore[arg-type]
        )
        t = ToolResult.from_adapter_result(
            tool="x", adapter_result=ar,
        )
        self.assertEqual(t.latency_ms, 0.0)
        self.assertEqual(t.cost_usd, 0.0)
        self.assertEqual(t.tokens_in, 0)


class TestMcpProtocolShape(unittest.TestCase):
    """The to_mcp() wire payload must still be
    protocol-conformant after the extension."""

    def test_ok_payload_has_content_array(self):
        t = ToolResult(
            tool="x", ok=True,
            content={"a": 1},
            cost_usd=0.001,
        )
        payload = t.to_mcp()
        self.assertEqual(payload["isError"], False)
        self.assertIsInstance(payload["content"], list)

    def test_error_payload_has_error_flag(self):
        t = ToolResult(
            tool="x", ok=False, error="boom",
        )
        payload = t.to_mcp()
        self.assertTrue(payload["isError"])
        self.assertIn("boom", payload["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
