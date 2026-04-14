"""Dashboard AI Assistant — conversation memory, slash commands, context.

Exercises the Option D wiring:

* Slash-command dispatch (`/status`, `/cycle`, `/vault`, `/health`, `/clear`,
  `/help`, and unknown-fallback) — all resolved without any LLM call.
* History clamping — malformed turns are dropped, the window is respected.
* Context snapshot — ``_build_chat_context`` must never raise even when
  every subsystem is offline, and the derived system prompt must embed
  the live counts when they're available.
* LLM path — payload shape passed to ``router.execute``.

Uses ``object.__new__`` to instantiate the handler without the HTTP
plumbing, so tests stay hermetic and fast."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from dashboard.app import DashboardAPIHandler


def _handler() -> DashboardAPIHandler:
    """Build a handler without triggering BaseHTTPRequestHandler.__init__."""
    return object.__new__(DashboardAPIHandler)


# ---------------------------------------------------------------------------
# Slash command routing
# ---------------------------------------------------------------------------


class TestSlashCommands:
    def test_help_command_lists_slash_syntax(self):
        h = _handler()
        out = h._handle_slash("/help")
        assert "/status" in out
        assert "/cycle" in out
        assert "/vault" in out
        assert "/clear" in out

    def test_clear_command_returns_confirmation(self):
        h = _handler()
        out = h._handle_slash("/clear")
        assert "cleared" in out.lower()

    def test_unknown_command_returns_help(self):
        h = _handler()
        out = h._handle_slash("/totallybogus")
        assert "Unknown command" in out
        assert "/status" in out  # help body appended

    def test_status_command_delegates_to_adapter_status(self, monkeypatch):
        h = _handler()
        monkeypatch.setattr(h, "_chat_adapter_status",
                            lambda: "**STATUS_SENTINEL**")
        assert h._handle_slash("/status") == "**STATUS_SENTINEL**"

    def test_adapters_alias_also_routes_to_status(self, monkeypatch):
        h = _handler()
        monkeypatch.setattr(h, "_chat_adapter_status",
                            lambda: "**STATUS_SENTINEL**")
        assert h._handle_slash("/adapters") == "**STATUS_SENTINEL**"

    def test_vault_command_delegates(self, monkeypatch):
        h = _handler()
        monkeypatch.setattr(h, "_chat_vault", lambda: "**VAULT_SENTINEL**")
        assert h._handle_slash("/vault") == "**VAULT_SENTINEL**"

    def test_slash_strips_leading_whitespace(self):
        h = _handler()
        # "  /help" isn't a slash per the caller contract, but a well-formed
        # "/help  " with trailing space still parses.
        out = h._handle_slash("/help   ")
        assert "/status" in out

    def test_slash_args_ignored_but_do_not_crash(self, monkeypatch):
        h = _handler()
        monkeypatch.setattr(h, "_chat_cycle", lambda: "**CYCLE**")
        # Arguments after the command are currently swallowed — ensure no
        # regression if a user types "/cycle now please".
        assert h._handle_slash("/cycle now please") == "**CYCLE**"


# ---------------------------------------------------------------------------
# _process_chat entry point
# ---------------------------------------------------------------------------


class TestProcessChat:
    def test_slash_skips_llm(self, monkeypatch):
        h = _handler()
        called = []
        monkeypatch.setattr(h, "_chat_via_llm",
                            lambda m, hist: called.append(("llm", m)))
        monkeypatch.setattr(h, "_chat_adapter_status",
                            lambda: "ok")
        assert h._process_chat("/status") == "ok"
        assert called == []

    def test_keyword_adapter_status_hits_local_handler(self, monkeypatch):
        h = _handler()
        monkeypatch.setattr(h, "_chat_adapter_status", lambda: "kw-status")
        # Keyword path: "adapter status".
        assert h._process_chat("adapter status") == "kw-status"

    def test_keyword_cycle_uses_cycle_handler(self, monkeypatch):
        h = _handler()
        monkeypatch.setattr(h, "_chat_cycle", lambda: "kw-cycle")
        assert h._process_chat("latest cycle?") == "kw-cycle"

    def test_mongolian_vault_keyword(self, monkeypatch):
        h = _handler()
        monkeypatch.setattr(h, "_chat_vault", lambda: "kw-vault")
        assert h._process_chat("ноут харуул") == "kw-vault"

    def test_fallthrough_invokes_llm_path(self, monkeypatch):
        h = _handler()
        calls: list = []

        def fake_llm(msg, hist):
            calls.append((msg, list(hist)))
            return "llm-reply"

        monkeypatch.setattr(h, "_chat_via_llm", fake_llm)
        out = h._process_chat("What should I do about my returns rate?", [])
        assert out == "llm-reply"
        assert calls and calls[0][0].startswith("What should")

    def test_history_forwarded_to_llm(self, monkeypatch):
        h = _handler()
        captured = {}

        def fake_llm(msg, hist):
            captured["msg"] = msg
            captured["hist"] = hist
            return "llm-ok"

        monkeypatch.setattr(h, "_chat_via_llm", fake_llm)
        hist = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello!"},
        ]
        h._process_chat("how are you?", hist)
        assert captured["hist"] is hist


# ---------------------------------------------------------------------------
# History clamping (_build_messages)
# ---------------------------------------------------------------------------


class TestBuildMessages:
    def test_empty_history_yields_single_user_turn(self):
        h = _handler()
        out = h._build_messages([], "hello")
        assert out == [{"role": "user", "content": "hello"}]

    def test_history_is_clamped_to_window(self):
        h = _handler()
        hist = [
            {"role": "user", "content": f"u{i}"} if i % 2 == 0
            else {"role": "assistant", "content": f"a{i}"}
            for i in range(20)
        ]
        out = h._build_messages(hist, "final")
        # Window + 1 appended user turn.
        assert len(out) == h._CHAT_HISTORY_WINDOW + 1
        assert out[-1] == {"role": "user", "content": "final"}

    def test_malformed_entries_dropped(self):
        h = _handler()
        hist = [
            "not a dict",                                  # dropped
            {"role": "system", "content": "bad role"},     # dropped
            {"role": "user"},                              # dropped: no content
            {"role": "user", "content": 42},               # dropped: non-str
            {"role": "user", "content": "valid"},          # kept
        ]
        out = h._build_messages(hist, "next")
        assert out == [
            {"role": "user", "content": "valid"},
            {"role": "user", "content": "next"},
        ]

    def test_content_truncated_to_2000_chars(self):
        h = _handler()
        long = "x" * 5000
        hist = [{"role": "user", "content": long}]
        out = h._build_messages(hist, "next")
        assert len(out[0]["content"]) == 2000


# ---------------------------------------------------------------------------
# _build_chat_context + _build_system_prompt
# ---------------------------------------------------------------------------


class TestContextBuilder:
    def test_empty_system_returns_safe_defaults(self, monkeypatch):
        h = _handler()
        # All subsystems raise.
        monkeypatch.setattr(h, "_get_adapter_status",
                            lambda: (_ for _ in ()).throw(RuntimeError("x")))
        monkeypatch.setattr(h, "_get_system_health",
                            lambda: (_ for _ in ()).throw(RuntimeError("x")))
        ctx = h._build_chat_context()
        assert ctx["adapters_total"] == 0
        assert ctx["adapters_configured"] == 0
        assert ctx["system_status"] == "unknown"
        assert ctx["cycle_summary"] == ""
        assert ctx["vault_summary"] == ""

    def test_populated_context_reflects_subsystems(self, monkeypatch):
        h = _handler()
        monkeypatch.setattr(h, "_get_adapter_status", lambda: {
            "total": 30, "configured": 7,
            "categories": {"llm": [], "crm": []},
        })
        monkeypatch.setattr(h, "_get_system_health",
                            lambda: {"status": "healthy"})
        # Scheduler singleton with a summary.
        fake_sched = MagicMock()
        fake_sched.get_last_summary.return_value = {
            "cycle_id": "cyc-99",
            "store_id": "deguar",
            "duration_s": 3.14,
            "phase_error_count": 0,
            "top_action": "update_pricing",
        }
        monkeypatch.setattr(
            "core.system.auto_scheduler.get_scheduler",
            lambda: fake_sched,
        )
        # Vault helper.
        monkeypatch.setattr(
            "dashboard.app._collect_vault_summary",
            lambda: {
                "configured": True,
                "totals": {"total": 27, "Wins": 3, "Errors": 1,
                           "Decisions": 5, "ShopAI/Learned": 2},
            },
        )
        ctx = h._build_chat_context()
        assert ctx["adapters_total"] == 30
        assert ctx["adapters_configured"] == 7
        assert ctx["adapters_categories"] == 2
        assert ctx["system_status"] == "healthy"
        assert "cyc-99" in ctx["cycle_summary"]
        assert "update_pricing" in ctx["cycle_summary"]
        assert "27 notes" in ctx["vault_summary"]
        assert "learned=2" in ctx["vault_summary"]

    def test_system_prompt_embeds_context(self, monkeypatch):
        h = _handler()
        monkeypatch.setattr(h, "_build_chat_context", lambda: {
            "adapters_total": 30,
            "adapters_configured": 5,
            "adapters_categories": 10,
            "system_status": "degraded",
            "cycle_summary": "cyc-42 store=x duration=1.0s errors=0 top_action=none",
            "vault_summary": "12 notes (wins=1 errors=0 decisions=2 learned=0)",
        })
        prompt = h._build_system_prompt()
        assert "5/30 online" in prompt
        assert "10 categories" in prompt
        assert "degraded" in prompt
        assert "cyc-42" in prompt
        assert "12 notes" in prompt
        # Slash command hint lives in the prompt so the LLM doesn't fight it.
        assert "/status" in prompt


# ---------------------------------------------------------------------------
# LLM fallback when no adapter is configured
# ---------------------------------------------------------------------------


class TestLLMFallback:
    def test_llm_failure_returns_friendly_hint(self, monkeypatch):
        h = _handler()

        def _boom(_cap, _params):
            raise RuntimeError("no llm")

        fake_router = MagicMock()
        fake_router.execute = _boom
        monkeypatch.setattr(
            "core.adapters.get_router", lambda: fake_router,
        )
        out = h._chat_via_llm("tell me a joke", [])
        assert "/status" in out
        assert "/help" in out

    def test_successful_llm_result_text_returned(self, monkeypatch):
        h = _handler()
        fake_result = MagicMock()
        fake_result.ok = True
        fake_result.data = {"text": "I'm ShopAI and I'm fine."}
        fake_router = MagicMock()
        fake_router.execute.return_value = fake_result
        monkeypatch.setattr(
            "core.adapters.get_router", lambda: fake_router,
        )
        # Avoid hitting any real adapter plumbing in the context builder.
        monkeypatch.setattr(h, "_build_chat_context", lambda: {
            "adapters_total": 0, "adapters_configured": 0,
            "adapters_categories": 0, "system_status": "unknown",
            "cycle_summary": "", "vault_summary": "",
        })

        out = h._chat_via_llm("hi", [])
        assert out == "I'm ShopAI and I'm fine."
        # Verify payload shape.
        _cap, params = fake_router.execute.call_args[0]
        assert "messages" in params
        assert params["messages"][-1]["content"] == "hi"
        assert params["max_tokens"] == 500
        assert "system" in params
