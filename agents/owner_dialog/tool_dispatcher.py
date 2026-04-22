"""Telegram message → MCP tool dispatcher.

Closes the "owner drives ShopAI from Telegram" loop. The owner
types a short natural phrase like:

    "halt launches"           → emergency_halt
    "trust scores"            → trust_status
    "moby win rate"           → moby_win_rate
    "is the daemon alive?"    → autopilot_status
    "doctor"                  → doctor
    "how much fal budget"     → fal_budget_status

…and gets back a Telegram reply formatted from the MCP tool's
result. No LLM required — this is a deterministic intent table
mapped to MCP tool names. LLM-free, predictable, easy to
audit.

Safety: every entry in the intent table declares whether the
backing tool is read-only or write. Write tools require the
owner to suffix the message with the word ``confirm`` (e.g.
"halt launches confirm"). Without confirm we reply with a
preview prompt instead of executing. This matches CLAUDE.md
§4b/G paranoid-mode "auto_approve or human approval" rule.

Pure stdlib + injectable registry / Telegram adapter. The
registry comes from ``mcp_server.tools.build_default_registry``
in production; tests inject a tiny test registry.
"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from typing import Any

from utils.logger import get_logger


logger = get_logger("agents.owner_dialog.tool_dispatcher")


@dataclass
class IntentMatch:
    """Result of parsing an owner message."""

    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)
    confirmed: bool = False
    write: bool = False
    raw_text: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "arguments": dict(self.arguments),
            "confirmed": self.confirmed,
            "write": self.write,
            "raw_text": self.raw_text,
        }


@dataclass
class DispatchResult:
    sent: bool
    intent: IntentMatch | None
    tool_ok: bool
    text: str
    message_id: int | None = None
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "sent": self.sent,
            "intent": (
                self.intent.as_dict()
                if self.intent else None
            ),
            "tool_ok": self.tool_ok,
            "text": self.text,
            "message_id": self.message_id,
            "reason": self.reason,
        }


# Intent → (tool_name, write?, [phrase regex patterns])
# Each pattern is a regex applied to the lowercased message
# (after stripping "confirm" suffix). First match wins.
_INTENT_TABLE: tuple[
    tuple[str, bool, tuple[str, ...]], ...,
] = (
    ("emergency_halt", True, (
        r"\bhalt\b",
        r"\bemergency\s+stop\b",
        r"\bkill\s+(launches|all)\b",
        r"\bstop\s+everything\b",
    )),
    ("emergency_resume", True, (
        r"\bresume\b",
        r"\bunpause\b",
        r"\bclear\s+halt\b",
    )),
    ("brain_snapshot", False, (
        r"\bbrain\s*(state|snapshot)?$",
        r"\bbrain\s*\?",
    )),
    ("risk_status", False, (
        r"\brisk\b",
        r"\btripwire\b",
    )),
    ("trust_status", False, (
        r"\btrust\b",
        r"\bsource\s+trust\b",
    )),
    ("moby_win_rate", False, (
        r"\bmoby\b",
        r"\bwin[-_ ]?rate\b",
        r"\btriple\s*whale\b",
    )),
    ("fal_budget_status", False, (
        r"\bfal\b",
        r"\bvideo\s+budget\b",
    )),
    ("agentic_channels", False, (
        r"\bagentic\b",
        r"\bchatgpt|perplexity|copilot|gemini\b",
    )),
    ("autopilot_status", False, (
        r"\b(autopilot|daemon)\s*(alive|running|status)?",
        r"\bis\s+(the\s+)?(autopilot|daemon)\s+(alive|on|running)\b",
    )),
    ("doctor", False, (
        r"\bdoctor\b",
        r"\bhealth\s*check\b",
        r"\b(is|are)\s+(everything|we)\s+connect",
    )),
    ("memory_ladder", False, (
        r"\bmemory\b",
        r"\bladder\b",
        r"\bconcepts\b",
    )),
    ("recent_decisions", False, (
        r"\brecent\s+decisions?\b",
        r"\blast\s+(\d+\s+)?decisions?\b",
    )),
    ("recent_cycles", False, (
        r"\bcycles?\b",
        r"\boverni(ght|te)\b",
        r"\blast\s+(\d+\s+)?cycles?\b",
    )),
    ("oauth_status", False, (
        r"\boauth\b",
        r"\btoken\s+status\b",
    )),
    ("webhook_rate_limit_status", False, (
        r"\bwebhook\s+(abuse|rate|limit)\b",
        r"\bspam(ming)?\s+webhook\b",
    )),
    ("notify_errors", True, (
        r"\bnotify\s+errors\b",
        r"\bsend\s+error\s+digest\b",
    )),
    ("list_rules", False, (
        r"\blist\s+rules\b",
        r"\b(top|learned)\s+(\d+\s+)?rules\b",
        r"\brulebook\b",
    )),
    ("ready_for_live", False, (
        r"\bready\s+(for\s+)?live\b",
        r"\bgo\s*-?\s*live\s+gate\b",
        r"\bpre\s*-?\s*t1\b",
        r"\bcan\s+(we|i)\s+go\s+live\b",
    )),
    ("live_health", False, (
        r"\blive\s*-?\s*health\b",
        r"\bhealth\s+trend\b",
        r"\bhow\s+healthy\b",
    )),
    ("rule_quality", False, (
        r"\brule\s+quality\b",
        r"\btrue\s*-?\s*positive(\s+rate)?\b",
        r"\b(rules?\s+)?lift\b",
    )),
    ("engine_feedback_stats", False, (
        r"\bengine\s+(feedback|stats|trend)\b",
        r"\bper\s*-?\s*engine\s+stats\b",
    )),
    ("brain_module_catalog", False, (
        r"\bbrain\s+(catalog|modules)\b",
        r"\bmodule\s+catalog\b",
    )),
)


_LIMIT_RE = re.compile(
    r"\blast\s+(\d+)\b|\btop\s+(\d+)\b",
)


def _parse_args(text: str, tool: str) -> dict[str, Any]:
    """Pull obvious args out of the raw text. Currently
    handles the ``limit`` integer that recent_* tools accept.
    Anything more sophisticated belongs in tool-specific
    parsers (out of scope for this commit)."""
    args: dict[str, Any] = {}
    m = _LIMIT_RE.search(text)
    if m and tool in (
        "recent_decisions", "recent_cycles",
        "list_rules",
    ):
        try:
            args["limit"] = int(m.group(1) or m.group(2))
        except (TypeError, ValueError):
            pass
    return args


_CONFIRM_RE = re.compile(
    r"\b(confirm|yes|do it|proceed)\b", re.IGNORECASE,
)


def parse_intent(text: str) -> IntentMatch | None:
    """Map an owner message to an MCP tool intent. Returns
    None when nothing matches — caller should reply with a
    "didn't understand" prompt rather than guessing."""
    if not text or not isinstance(text, str):
        return None
    raw = text.strip()
    confirmed = bool(_CONFIRM_RE.search(raw))
    # Strip the confirm word from intent matching so
    # "halt launches confirm" still matches the halt regex.
    cleaned = _CONFIRM_RE.sub("", raw).strip().lower()
    for tool, write, patterns in _INTENT_TABLE:
        for pat in patterns:
            if re.search(pat, cleaned):
                args = _parse_args(cleaned, tool)
                return IntentMatch(
                    tool=tool,
                    arguments=args,
                    confirmed=confirmed,
                    write=write,
                    raw_text=raw,
                )
    return None


# ── Reply formatting ─────────────────────────────────────


def _format_value(value: Any, depth: int = 0) -> str:
    """Render an MCP tool result into Telegram-friendly
    plain text. Caps depth + length so a runaway list of
    1000 rules doesn't blow up the message."""
    if depth > 4:
        return "…"
    if isinstance(value, dict):
        if not value:
            return "{}"
        lines: list[str] = []
        for k, v in list(value.items())[:30]:
            inner = _format_value(v, depth + 1)
            if "\n" in inner:
                lines.append(f"{k}:\n{inner}")
            else:
                lines.append(f"{k}: {inner}")
        return "\n".join(
            "  " * depth + line for line in lines
        )
    if isinstance(value, list):
        if not value:
            return "[]"
        items = []
        for v in value[:20]:
            items.append(
                "- " + _format_value(v, depth + 1),
            )
        suffix = (
            f"\n…({len(value) - 20} more)"
            if len(value) > 20 else ""
        )
        return "\n".join(items) + suffix
    if isinstance(value, float):
        return f"{value:.4f}"
    text = str(value)
    return text[:400] + ("…" if len(text) > 400 else "")


def format_reply(intent: IntentMatch, tool_result) -> str:
    """Compose a Telegram-bound reply from a ToolResult."""
    head = (
        f"✓ {intent.tool}"
        if tool_result.ok
        else f"✗ {intent.tool}"
    )
    if not tool_result.ok:
        return f"{head}\n{tool_result.error}"
    body = _format_value(tool_result.content)
    if not body:
        body = "(empty)"
    return f"{head}\n{body[:3500]}"


# ── Dispatcher ───────────────────────────────────────────


class OwnerToolDispatcher:
    """Stateless coordinator: parse → confirm-gate → call →
    format → send."""

    def __init__(
        self,
        *,
        registry: Any = None,
        telegram: Any = None,
    ) -> None:
        self._registry = registry
        self._telegram = telegram
        self._lock = threading.Lock()

    def _get_registry(self) -> Any:
        if self._registry is not None:
            return self._registry
        from mcp_server.tools import (
            build_default_registry,
        )
        self._registry = build_default_registry()
        return self._registry

    def _get_telegram(self) -> Any:
        if self._telegram is not None:
            return self._telegram
        from core.adapters.telegram_bot import (
            TelegramBotAdapter,
        )
        self._telegram = TelegramBotAdapter()
        return self._telegram

    def dispatch(
        self,
        text: str,
        *,
        chat_id: str | None = None,
        send: bool = True,
    ) -> DispatchResult:
        intent = parse_intent(text)
        if intent is None:
            reply = (
                "Sorry, I didn't recognise that. Try: "
                "halt launches | trust | moby | doctor | "
                "brain | risk | recent decisions | cycles."
            )
            return self._maybe_send(
                reply, intent=None,
                tool_ok=False,
                send=send, chat_id=chat_id,
                reason="no_intent",
            )
        if intent.write and not intent.confirmed:
            reply = (
                f"⚠ {intent.tool} is a write action. Reply "
                f"with the same message + 'confirm' to "
                f"execute.\nExample: '{text} confirm'"
            )
            return self._maybe_send(
                reply, intent=intent,
                tool_ok=False, send=send,
                chat_id=chat_id,
                reason="needs_confirm",
            )
        registry = self._get_registry()
        try:
            from mcp_server.tools import ToolCall
            result = registry.call(ToolCall(
                tool=intent.tool,
                arguments=intent.arguments,
            ))
        except Exception as exc:  # noqa: BLE001
            return self._maybe_send(
                f"✗ {intent.tool}: dispatcher raised {exc}",
                intent=intent,
                tool_ok=False,
                send=send, chat_id=chat_id,
                reason=f"dispatch_raised: {exc}",
            )
        text_out = format_reply(intent, result)
        return self._maybe_send(
            text_out,
            intent=intent,
            tool_ok=bool(result.ok),
            send=send,
            chat_id=chat_id,
        )

    def _maybe_send(
        self,
        text: str,
        *,
        intent: IntentMatch | None,
        tool_ok: bool,
        send: bool,
        chat_id: str | None,
        reason: str = "",
    ) -> DispatchResult:
        if not send:
            return DispatchResult(
                sent=False,
                intent=intent,
                tool_ok=tool_ok,
                text=text,
                reason=reason or "send=False",
            )
        adapter = self._get_telegram()
        if not getattr(
            adapter, "is_available", lambda: False,
        )():
            return DispatchResult(
                sent=False,
                intent=intent,
                tool_ok=tool_ok,
                text=text,
                reason=(
                    "telegram not configured — set "
                    "TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID"
                ),
            )
        try:
            mid = adapter.send_message(
                text, chat_id=chat_id,
            )
        except Exception as exc:  # noqa: BLE001
            return DispatchResult(
                sent=False,
                intent=intent,
                tool_ok=tool_ok,
                text=text,
                reason=f"send raised: {exc}",
            )
        if mid is None:
            return DispatchResult(
                sent=False,
                intent=intent,
                tool_ok=tool_ok,
                text=text,
                reason="send returned None",
            )
        return DispatchResult(
            sent=True,
            intent=intent,
            tool_ok=tool_ok,
            text=text,
            message_id=int(mid),
            reason=reason,
        )
