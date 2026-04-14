"""Dashboard chat tool-calling — Option F.

Exercises the prompt-based tool-use loop in ``_chat_via_llm``:

* ``_parse_tool_directive`` — isolates a single ``TOOL_CALL: {...}``
  directive from the first non-empty line and rejects malformed or
  natural-language replies.
* ``_run_chat_tool`` — dispatches to the ``_tool_*`` handlers, returns
  a JSON envelope, and never raises even when the tool itself does.
* ``_tool_get_*`` handlers — return well-shaped dicts, tolerate the
  underlying system being absent (no scheduler, no vault, no adapters).
* ``_chat_via_llm`` — runs one tool iteration when the first response
  contains a directive, then composes the final answer without chaining
  a second tool call.
* System prompt — advertises every tool in ``_CHAT_TOOLS``.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from dashboard.app import DashboardAPIHandler


def _handler() -> DashboardAPIHandler:
    return object.__new__(DashboardAPIHandler)


# ---------------------------------------------------------------------------
# _parse_tool_directive
# ---------------------------------------------------------------------------


class TestParseToolDirective:
    def test_plain_directive(self):
        out = DashboardAPIHandler._parse_tool_directive(
            'TOOL_CALL: {"tool": "get_cycle_summary"}',
        )
        assert out == {"tool": "get_cycle_summary"}

    def test_directive_with_args(self):
        out = DashboardAPIHandler._parse_tool_directive(
            'TOOL_CALL: {"tool": "x", "args": {"a": 1}}',
        )
        assert out == {"tool": "x", "args": {"a": 1}}

    def test_strips_leading_whitespace(self):
        out = DashboardAPIHandler._parse_tool_directive(
            '   TOOL_CALL: {"tool": "get_vault_summary"}',
        )
        assert out == {"tool": "get_vault_summary"}

    def test_natural_language_reply_returns_none(self):
        out = DashboardAPIHandler._parse_tool_directive(
            "Your system has 3 adapters online.",
        )
        assert out is None

    def test_empty_text_returns_none(self):
        assert DashboardAPIHandler._parse_tool_directive("") is None
        assert DashboardAPIHandler._parse_tool_directive(None) is None

    def test_malformed_json_returns_none(self):
        out = DashboardAPIHandler._parse_tool_directive(
            "TOOL_CALL: {tool: no quotes}",
        )
        assert out is None

    def test_missing_tool_key_returns_none(self):
        out = DashboardAPIHandler._parse_tool_directive(
            'TOOL_CALL: {"foo": "bar"}',
        )
        assert out is None

    def test_non_object_json_returns_none(self):
        out = DashboardAPIHandler._parse_tool_directive(
            'TOOL_CALL: ["get_cycle_summary"]',
        )
        assert out is None

    def test_directive_only_scanned_on_first_nonempty_line(self):
        # If the LLM starts with a natural reply, later quoted TOOL_CALL
        # strings must not trigger a tool call.
        out = DashboardAPIHandler._parse_tool_directive(
            'Here is how you would call it:\nTOOL_CALL: {"tool": "x"}',
        )
        assert out is None

    def test_ignores_trailing_junk_after_object(self):
        out = DashboardAPIHandler._parse_tool_directive(
            'TOOL_CALL: {"tool": "a"}  // comment',
        )
        assert out == {"tool": "a"}


# ---------------------------------------------------------------------------
# _run_chat_tool
# ---------------------------------------------------------------------------


class TestRunChatTool:
    def test_unknown_tool_returns_error_envelope(self):
        h = _handler()
        out = h._run_chat_tool("not_a_tool", {})
        assert "unknown tool" in json.loads(out)["error"]

    def test_handler_exception_caught(self, monkeypatch):
        h = _handler()
        # Inject a fake tool into the catalog + a boom handler.
        monkeypatch.setitem(
            DashboardAPIHandler._CHAT_TOOLS,
            "boom_tool",
            {"description": "test"},
        )

        def _boom(args):
            raise RuntimeError("kaboom")

        h._tool_boom_tool = _boom  # type: ignore[attr-defined]
        out = h._run_chat_tool("boom_tool", {})
        assert "kaboom" in json.loads(out)["error"]

    def test_success_returns_json_string(self, monkeypatch):
        h = _handler()
        monkeypatch.setitem(
            DashboardAPIHandler._CHAT_TOOLS,
            "echo_tool",
            {"description": "echo"},
        )
        h._tool_echo_tool = lambda args: {"ok": True, "got": args}  # type: ignore[attr-defined]
        out = h._run_chat_tool("echo_tool", {"a": 1})
        data = json.loads(out)
        assert data == {"ok": True, "got": {"a": 1}}

    def test_truncates_huge_output(self, monkeypatch):
        h = _handler()
        monkeypatch.setitem(
            DashboardAPIHandler._CHAT_TOOLS,
            "big_tool",
            {"description": "big"},
        )
        h._tool_big_tool = lambda args: {"x": "a" * 5000}  # type: ignore[attr-defined]
        out = h._run_chat_tool("big_tool", {})
        assert len(out) <= 2000


# ---------------------------------------------------------------------------
# _tool_get_* handlers
# ---------------------------------------------------------------------------


class TestAdapterStatusTool:
    def test_shape(self, monkeypatch):
        h = _handler()
        monkeypatch.setattr(h, "_get_adapter_status", lambda: {
            "total": 3, "configured": 2,
            "categories": {
                "llm": [
                    {"name": "groq", "configured": True},
                    {"name": "gemini", "configured": True},
                ],
                "shopify": [{"name": "products", "configured": False}],
            },
        })
        out = h._tool_get_adapter_status({})
        assert out["total"] == 3
        assert out["configured"] == 2
        assert out["categories"] == {"llm": 2, "shopify": 1}
        names = {a["name"] for a in out["adapters"]}
        assert names == {"groq", "gemini", "products"}

    def test_tolerates_empty(self, monkeypatch):
        h = _handler()
        monkeypatch.setattr(h, "_get_adapter_status", lambda: {})
        out = h._tool_get_adapter_status({})
        assert out["total"] == 0
        assert out["adapters"] == []


class TestCycleSummaryTool:
    def test_populated(self, monkeypatch):
        h = _handler()
        fake = MagicMock()
        fake.get_last_summary.return_value = {
            "cycle_id": "c1", "store_id": "acme",
            "duration_s": 1.5, "phase_error_count": 0,
            "actions_proposed": 4, "top_action": "restock",
        }
        fake.get_status.return_value = {
            "running": True, "busy": False, "cycles_run": 7,
            "last_error": None,
        }
        monkeypatch.setattr(
            "core.system.auto_scheduler.get_scheduler", lambda: fake,
        )
        out = h._tool_get_cycle_summary({})
        assert out["has_data"] is True
        assert out["latest"]["cycle_id"] == "c1"
        assert out["scheduler"]["cycles_run"] == 7

    def test_empty_when_no_cycle(self, monkeypatch):
        h = _handler()
        fake = MagicMock()
        fake.get_last_summary.return_value = None
        fake.get_status.return_value = {"running": False}
        monkeypatch.setattr(
            "core.system.auto_scheduler.get_scheduler", lambda: fake,
        )
        out = h._tool_get_cycle_summary({})
        assert out["has_data"] is False
        assert out["latest"]["cycle_id"] is None

    def test_fails_soft_when_scheduler_import_breaks(self, monkeypatch):
        h = _handler()

        def _boom():
            raise RuntimeError("no scheduler")

        monkeypatch.setattr(
            "core.system.auto_scheduler.get_scheduler", _boom,
        )
        out = h._tool_get_cycle_summary({})
        assert "error" in out


class TestVaultSummaryTool:
    def test_unconfigured(self, monkeypatch):
        h = _handler()
        monkeypatch.setattr(
            "dashboard.app._collect_vault_summary",
            lambda: {"configured": False},
        )
        out = h._tool_get_vault_summary({})
        assert out["configured"] is False
        assert out["recent"]["wins"] == []

    def test_configured(self, monkeypatch):
        h = _handler()
        monkeypatch.setattr(
            "dashboard.app._collect_vault_summary",
            lambda: {
                "configured": True,
                "path": "/vault",
                "totals": {"total": 10, "Wins": 2, "Errors": 1},
                "recent_wins": [{"title": "w1"}, {"title": "w2"}],
                "recent_errors": [{"title": "e1"}],
                "recent_decisions": [],
                "recent_learned": [{"title": "l1"}] * 20,
            },
        )
        out = h._tool_get_vault_summary({})
        assert out["configured"] is True
        assert out["totals"]["total"] == 10
        # Trimmed to 5.
        assert len(out["recent"]["learned"]) == 5
        assert len(out["recent"]["wins"]) == 2


# ---------------------------------------------------------------------------
# _chat_via_llm — tool-use loop
# ---------------------------------------------------------------------------


class TestChatViaLLMToolLoop:
    def test_no_directive_returns_direct_answer(self, monkeypatch):
        h = _handler()
        monkeypatch.setattr(h, "_build_system_prompt", lambda *a, **k: "sys")
        monkeypatch.setattr(h, "_build_messages",
                            lambda hist, msg: [{"role": "user", "content": msg}])

        fake_router = MagicMock()
        fake_router.execute.return_value = MagicMock(
            ok=True, data={"text": "3 adapters online."},
        )
        monkeypatch.setattr(
            "core.adapters.get_router", lambda: fake_router,
        )

        out = h._chat_via_llm("how many adapters?", [])
        assert out == "3 adapters online."
        assert fake_router.execute.call_count == 1

    def test_directive_runs_tool_then_composes(self, monkeypatch):
        h = _handler()
        monkeypatch.setattr(h, "_build_system_prompt", lambda *a, **k: "sys")
        monkeypatch.setattr(h, "_build_messages",
                            lambda hist, msg: [{"role": "user", "content": msg}])

        calls = {"n": 0}

        def _execute(cap, params):
            calls["n"] += 1
            if calls["n"] == 1:
                return MagicMock(
                    ok=True,
                    data={"text": 'TOOL_CALL: {"tool": "get_cycle_summary"}'},
                )
            # Second call must include the tool result in messages.
            joined = json.dumps(params["messages"])
            assert "TOOL_RESULT for get_cycle_summary" in joined
            return MagicMock(
                ok=True, data={"text": "Latest cycle ran for 1.5s."},
            )

        fake_router = MagicMock()
        fake_router.execute.side_effect = _execute
        monkeypatch.setattr(
            "core.adapters.get_router", lambda: fake_router,
        )
        monkeypatch.setattr(
            h, "_run_chat_tool",
            lambda name, args: '{"latest": {"duration_s": 1.5}}',
        )

        out = h._chat_via_llm("what did the cycle do?", [])
        assert out == "Latest cycle ran for 1.5s."
        assert calls["n"] == 2

    def test_loop_capped_at_two_iterations(self, monkeypatch):
        h = _handler()
        monkeypatch.setattr(h, "_build_system_prompt", lambda *a, **k: "sys")
        monkeypatch.setattr(h, "_build_messages",
                            lambda hist, msg: [{"role": "user", "content": msg}])

        # Always issue a TOOL_CALL — the second iteration must stop the
        # loop and return that raw text rather than spinning forever.
        fake_router = MagicMock()
        fake_router.execute.return_value = MagicMock(
            ok=True,
            data={"text": 'TOOL_CALL: {"tool": "get_cycle_summary"}'},
        )
        monkeypatch.setattr(
            "core.adapters.get_router", lambda: fake_router,
        )
        monkeypatch.setattr(
            h, "_run_chat_tool", lambda name, args: '{}',
        )

        out = h._chat_via_llm("loop?", [])
        # Two executes total — one for the original, one for the "final"
        # retry that still returned a directive.
        assert fake_router.execute.call_count == 2
        assert "TOOL_CALL" in out  # Returned as-is since the loop hit the cap.

    def test_router_miss_falls_back_to_help(self, monkeypatch):
        h = _handler()

        def _boom():
            raise RuntimeError("no router")

        monkeypatch.setattr(
            "core.adapters.get_router", _boom,
        )
        out = h._chat_via_llm("hi", [])
        assert "LLM adapter" in out
        assert "/status" in out


# ---------------------------------------------------------------------------
# System prompt — tool advertisement
# ---------------------------------------------------------------------------


class TestSystemPromptMentionsTools:
    def test_catalog_rendered(self, monkeypatch):
        h = _handler()
        # Context collectors may blow up depending on environment;
        # short-circuit them for a hermetic test.
        monkeypatch.setattr(h, "_build_chat_context", lambda: {
            "adapters_total": 1, "adapters_configured": 1,
            "adapters_categories": 1, "system_status": "ok",
            "cycle_summary": "", "vault_summary": "",
        })
        prompt = h._build_system_prompt()
        assert "TOOL_CALL:" in prompt
        for name in DashboardAPIHandler._CHAT_TOOLS:
            assert name in prompt
