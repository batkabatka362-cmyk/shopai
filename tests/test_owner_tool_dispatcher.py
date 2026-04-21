"""Tests for the owner_dialog tool dispatcher (P1.3)."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from agents.owner_dialog.tool_dispatcher import (
    DispatchResult,
    IntentMatch,
    OwnerToolDispatcher,
    _format_value,
    format_reply,
    parse_intent,
)
from mcp_server.tools import (
    ToolCall,
    ToolRegistry,
    ToolResult,
    ToolSpec,
)


def _registry_with(handlers: dict, write: set[str] | None = None):
    write = write or set()
    reg = ToolRegistry()
    for name, fn in handlers.items():
        reg.register(ToolSpec(
            name=name,
            description=name,
            input_schema={
                "type": "object", "properties": {},
            },
            handler=fn,
            write=name in write,
        ))
    return reg


def _telegram_ok(message_id=999):
    t = MagicMock()
    t.is_available.return_value = True
    t.send_message.return_value = message_id
    return t


# ── parse_intent ──────────────────────────────────────────


class TestParseIntent(unittest.TestCase):
    def test_halt_matches(self):
        i = parse_intent("halt launches")
        self.assertIsNotNone(i)
        self.assertEqual(i.tool, "emergency_halt")
        self.assertTrue(i.write)
        self.assertFalse(i.confirmed)

    def test_halt_with_confirm(self):
        i = parse_intent("halt launches confirm")
        self.assertEqual(i.tool, "emergency_halt")
        self.assertTrue(i.confirmed)

    def test_trust_scores(self):
        i = parse_intent("trust scores")
        self.assertEqual(i.tool, "trust_status")
        self.assertFalse(i.write)

    def test_doctor(self):
        i = parse_intent("doctor")
        self.assertEqual(i.tool, "doctor")

    def test_moby_win_rate(self):
        i = parse_intent("how is moby?")
        self.assertEqual(i.tool, "moby_win_rate")

    def test_autopilot_alive(self):
        i = parse_intent(
            "is the daemon alive?",
        )
        self.assertEqual(i.tool, "autopilot_status")

    def test_recent_decisions_with_limit(self):
        i = parse_intent("last 5 decisions")
        self.assertEqual(i.tool, "recent_decisions")
        self.assertEqual(i.arguments.get("limit"), 5)

    def test_recent_cycles_default_no_limit(self):
        i = parse_intent("show me cycles")
        self.assertEqual(i.tool, "recent_cycles")
        self.assertNotIn("limit", i.arguments)

    def test_top_n_rules(self):
        i = parse_intent("top 7 rules")
        self.assertEqual(i.tool, "list_rules")
        self.assertEqual(i.arguments.get("limit"), 7)

    def test_no_match_returns_none(self):
        self.assertIsNone(
            parse_intent("hello there"),
        )
        self.assertIsNone(parse_intent(""))
        self.assertIsNone(parse_intent(None))  # type: ignore[arg-type]

    def test_resume_is_write(self):
        i = parse_intent("resume")
        self.assertEqual(i.tool, "emergency_resume")
        self.assertTrue(i.write)

    def test_notify_errors_is_write(self):
        i = parse_intent("notify errors")
        self.assertTrue(i.write)


# ── format_value ──────────────────────────────────────────


class TestFormatting(unittest.TestCase):
    def test_dict_formatted(self):
        out = _format_value({"a": 1, "b": "x"})
        self.assertIn("a: 1", out)
        self.assertIn("b: x", out)

    def test_list_capped(self):
        out = _format_value(list(range(50)))
        self.assertIn("- 0", out)
        self.assertIn("more", out)

    def test_long_string_truncated(self):
        s = "x" * 600
        out = _format_value(s)
        self.assertTrue(out.endswith("…"))

    def test_format_reply_ok(self):
        intent = IntentMatch(tool="trust_status")
        result = ToolResult(
            tool="trust_status",
            ok=True,
            content={"a": 1},
        )
        reply = format_reply(intent, result)
        self.assertIn("✓ trust_status", reply)
        self.assertIn("a: 1", reply)

    def test_format_reply_error(self):
        intent = IntentMatch(tool="moby_win_rate")
        result = ToolResult(
            tool="moby_win_rate",
            ok=False,
            error="boom",
        )
        reply = format_reply(intent, result)
        self.assertIn("✗ moby_win_rate", reply)
        self.assertIn("boom", reply)


# ── Dispatcher ───────────────────────────────────────────


class TestDispatcher(unittest.TestCase):
    def test_no_intent_returns_help_message(self):
        dispatcher = OwnerToolDispatcher(
            registry=_registry_with({
                "trust_status": lambda a: {"x": 1},
            }),
            telegram=_telegram_ok(),
        )
        result = dispatcher.dispatch("hello world")
        self.assertTrue(result.sent)
        self.assertIsNone(result.intent)
        self.assertIn("didn't recognise", result.text.lower())

    def test_read_only_tool_executed(self):
        dispatcher = OwnerToolDispatcher(
            registry=_registry_with({
                "trust_status": lambda a: [
                    {"source": "x", "trust": 0.5},
                ],
            }),
            telegram=_telegram_ok(),
        )
        result = dispatcher.dispatch("trust scores")
        self.assertTrue(result.sent)
        self.assertEqual(
            result.intent.tool, "trust_status",
        )
        self.assertTrue(result.tool_ok)
        self.assertIn("trust_status", result.text)

    def test_write_tool_requires_confirm(self):
        called = []
        dispatcher = OwnerToolDispatcher(
            registry=_registry_with(
                {"emergency_halt": lambda a: called.append(a) or {}},
                write={"emergency_halt"},
            ),
            telegram=_telegram_ok(),
        )
        result = dispatcher.dispatch("halt launches")
        self.assertTrue(result.sent)
        self.assertEqual(called, [])
        self.assertIn("confirm", result.text.lower())
        self.assertEqual(result.reason, "needs_confirm")

    def test_write_tool_with_confirm_executes(self):
        called = []

        def _h(a):
            called.append(a)
            return {"halted": True}

        dispatcher = OwnerToolDispatcher(
            registry=_registry_with(
                {"emergency_halt": _h},
                write={"emergency_halt"},
            ),
            telegram=_telegram_ok(),
        )
        result = dispatcher.dispatch(
            "halt launches confirm",
        )
        self.assertTrue(result.sent)
        self.assertEqual(len(called), 1)
        self.assertTrue(result.tool_ok)

    def test_send_false_returns_text_only(self):
        dispatcher = OwnerToolDispatcher(
            registry=_registry_with({
                "doctor": lambda a: {"ok": True},
            }),
            telegram=_telegram_ok(),
        )
        result = dispatcher.dispatch(
            "doctor", send=False,
        )
        self.assertFalse(result.sent)
        self.assertEqual(result.reason, "send=False")
        self.assertIn("doctor", result.text)

    def test_unconfigured_telegram_surfaces_reason(self):
        t = MagicMock()
        t.is_available.return_value = False
        dispatcher = OwnerToolDispatcher(
            registry=_registry_with({
                "doctor": lambda a: {"ok": True},
            }),
            telegram=t,
        )
        result = dispatcher.dispatch("doctor")
        self.assertFalse(result.sent)
        self.assertIn(
            "telegram not configured", result.reason,
        )

    def test_send_returns_none_surfaces_reason(self):
        t = MagicMock()
        t.is_available.return_value = True
        t.send_message.return_value = None
        dispatcher = OwnerToolDispatcher(
            registry=_registry_with({
                "doctor": lambda a: {"ok": True},
            }),
            telegram=t,
        )
        result = dispatcher.dispatch("doctor")
        self.assertFalse(result.sent)
        self.assertIn("None", result.reason)

    def test_tool_handler_error_reported_in_reply(self):
        def _bad(a):
            raise RuntimeError("kaboom")
        dispatcher = OwnerToolDispatcher(
            registry=_registry_with({"doctor": _bad}),
            telegram=_telegram_ok(),
        )
        result = dispatcher.dispatch("doctor")
        self.assertTrue(result.sent)
        self.assertFalse(result.tool_ok)
        self.assertIn("doctor", result.text)
        self.assertIn("kaboom", result.text)

    def test_recent_decisions_passes_limit(self):
        captured = []

        def _h(args):
            captured.append(args)
            return [{"id": "d1"}]

        dispatcher = OwnerToolDispatcher(
            registry=_registry_with({
                "recent_decisions": _h,
            }),
            telegram=_telegram_ok(),
        )
        dispatcher.dispatch("last 3 decisions")
        self.assertEqual(captured[0].get("limit"), 3)


if __name__ == "__main__":
    unittest.main()
