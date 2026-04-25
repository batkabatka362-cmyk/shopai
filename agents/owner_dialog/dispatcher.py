"""Owner dialog dispatcher — map Telegram commands to brain actions.

Wire-in #3/5. TelegramBotAdapter (b8cddf0) exposes
``poll_commands()`` that returns parsed verbs + args. notify_owner
(27ce123) pushes digests out. This module closes the loop: pull
the owner's replies, dispatch each verb to a handler, and push a
confirmation back to the chat.

Design:
  * Dispatcher is pure wiring — handlers are injected callables so
    tests never touch the real brain or network.
  * Handlers receive (args: tuple[str, ...]) and return a str
    reply. Exceptions are caught and surfaced as error replies;
    the dispatcher never raises.
  * Default ``build_default_handlers()`` factory wires verbs to
    the real brain / tripwire / crisis / revision_journal so
    ``shopai owner poll`` just works.
  * Supported verbs: approve, approve_all, reject, reject_all,
    status, limits, pause, resume, digest, help.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from utils.logger import get_logger


logger = get_logger("agents.owner_dialog.dispatcher")


Handler = Callable[[tuple[str, ...]], str]


_HELP_TEXT = (
    "*ShopAI commands*\n"
    "• `approve <id>` / `approve_all`\n"
    "• `reject <id>` / `reject_all`\n"
    "• `status`      — crisis + tripwire state\n"
    "• `limits`      — show tripwire caps\n"
    "• `pause`       — engage emergency halt\n"
    "• `resume`      — clear the halt\n"
    "• `digest`      — run launch digest now\n"
    "• `help`        — this message"
)


@dataclass
class DispatchResult:
    update_id: int
    verb: str
    args: tuple[str, ...] = ()
    reply: str = ""
    ok: bool = True
    error: str = ""
    sent_message_id: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "update_id": self.update_id,
            "verb": self.verb,
            "args": list(self.args),
            "reply": self.reply,
            "ok": self.ok,
            "error": self.error,
            "sent_message_id": self.sent_message_id,
        }


class OwnerDialogDispatcher:
    """Poll Telegram → dispatch commands → push replies."""

    def __init__(
        self,
        *,
        bot: Any,
        handlers: dict[str, Handler] | None = None,
    ) -> None:
        if bot is None:
            raise ValueError("bot required")
        self._bot = bot
        self._lock = threading.Lock()
        self._handlers: dict[str, Handler] = dict(
            handlers or {},
        )
        self._history: list[DispatchResult] = []

    def register(self, verb: str, handler: Handler) -> None:
        if not verb:
            raise ValueError("verb required")
        with self._lock:
            self._handlers[verb] = handler

    def handlers(self) -> dict[str, Handler]:
        with self._lock:
            return dict(self._handlers)

    # ── Poll + dispatch ──────────────────────────────────

    def poll_and_dispatch(
        self,
        *,
        limit: int = 20,
        reply: bool = True,
    ) -> list[DispatchResult]:
        if not getattr(self._bot, "is_available", None):
            return []
        if not self._bot.is_available():
            return []
        try:
            commands = self._bot.poll_commands(limit=limit)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "poll_commands raised: %s", exc,
            )
            return []
        results: list[DispatchResult] = []
        with self._lock:
            handlers = dict(self._handlers)
        for cmd in commands:
            result = self._dispatch_one(
                cmd, handlers=handlers, reply=reply,
            )
            results.append(result)
        with self._lock:
            self._history.extend(results)
            if len(self._history) > 200:
                self._history = self._history[-200:]
        return results

    def _dispatch_one(
        self,
        cmd: Any,
        *,
        handlers: dict[str, Handler],
        reply: bool,
    ) -> DispatchResult:
        upd = cmd.update
        update_id = (
            int(upd.update_id) if upd is not None else 0
        )
        verb = cmd.verb or ""
        args = cmd.args
        if not verb:
            result = DispatchResult(
                update_id=update_id,
                verb="",
                args=args,
                reply=(
                    "Unknown command. Type `help` for the "
                    "list of supported commands."
                ),
                ok=False,
                error="unknown verb",
            )
        elif verb == "help":
            result = DispatchResult(
                update_id=update_id,
                verb=verb,
                args=args,
                reply=_HELP_TEXT,
                ok=True,
            )
        elif verb not in handlers:
            result = DispatchResult(
                update_id=update_id,
                verb=verb,
                args=args,
                reply=f"No handler registered for `{verb}`.",
                ok=False,
                error="no handler",
            )
        else:
            try:
                reply_text = handlers[verb](args)
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "handler %s raised: %s", verb, exc,
                )
                result = DispatchResult(
                    update_id=update_id,
                    verb=verb,
                    args=args,
                    reply=(
                        f"Handler `{verb}` failed: {exc}"
                    ),
                    ok=False,
                    error=str(exc),
                )
            else:
                result = DispatchResult(
                    update_id=update_id,
                    verb=verb,
                    args=args,
                    reply=str(reply_text or ""),
                    ok=True,
                )
        if reply and result.reply:
            try:
                mid = self._bot.send_message(
                    result.reply,
                )
                if mid is not None:
                    result.sent_message_id = int(mid)
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "bot.send_message failed: %s", exc,
                )
                result.error = (
                    (result.error or "")
                    + f"; send_failed: {exc}"
                )
        return result

    def history(
        self, *, limit: int = 50,
    ) -> list[DispatchResult]:
        with self._lock:
            return list(self._history[-int(limit):])


# ── Default handlers ───────────────────────────────────────


def build_default_handlers() -> dict[str, Handler]:
    """Wire the supported verbs to real brain singletons.

    Each handler is thin — it pulls the singleton lazily and
    formats a chat-friendly reply string. Exceptions are caught
    at the dispatcher layer, so handler code can be straight-
    forward.
    """

    def _approve(args: tuple[str, ...]) -> str:
        if not args:
            return (
                "Usage: `approve <revision_id>` — or "
                "`approve_all` for every pending proposal."
            )
        from core.brain.brain_facade import (
            _revision_journal,
        )
        journal = _revision_journal()
        rev = journal.accept(args[0])
        return (
            f"✓ Accepted `{rev.id[:10]}` "
            f"(target={rev.target})"
        )

    def _approve_all(args: tuple[str, ...]) -> str:
        from core.brain.brain_facade import (
            _revision_journal,
        )
        journal = _revision_journal()
        pending = journal.by_status("proposed")
        count = 0
        for rev in pending:
            try:
                journal.accept(rev.id)
                count += 1
            except Exception:  # noqa: BLE001
                pass
        return f"✓ Accepted {count} pending proposal(s)."

    def _reject(args: tuple[str, ...]) -> str:
        if not args:
            return "Usage: `reject <revision_id>`"
        from core.brain.brain_facade import (
            _revision_journal,
        )
        journal = _revision_journal()
        rev = journal.reject(args[0])
        return f"✗ Rejected `{rev.id[:10]}`"

    def _reject_all(args: tuple[str, ...]) -> str:
        from core.brain.brain_facade import (
            _revision_journal,
        )
        journal = _revision_journal()
        pending = journal.by_status("proposed")
        count = 0
        for rev in pending:
            try:
                journal.reject(rev.id)
                count += 1
            except Exception:  # noqa: BLE001
                pass
        return f"✗ Rejected {count} pending proposal(s)."

    def _status(args: tuple[str, ...]) -> str:
        from core.crisis.response import (
            get_crisis_responder,
        )
        from core.risk.tripwire import get_risk_tripwire
        crisis = get_crisis_responder().detect_state()
        risk = get_risk_tripwire().status()
        return (
            f"*Crisis*: {crisis.level}  "
            f"(halted={crisis.halted})\n"
            f"*Risk today*: "
            f"${risk['today']['ad_spend_usd']:.2f} / "
            f"${risk['limits']['daily_ad_spend_usd']:.2f}  "
            f"({risk['today']['utilisation']:.0%})"
        )

    def _limits(args: tuple[str, ...]) -> str:
        from core.risk.tripwire import get_risk_tripwire
        lim = get_risk_tripwire().limits().as_dict()
        return (
            f"*Caps*: daily ${lim['daily_ad_spend_usd']:.0f} · "
            f"per-campaign "
            f"${lim['per_campaign_cap_usd']:.0f} · "
            f"margin floor {lim['min_margin_ratio']:.0%} · "
            f"chargeback max "
            f"{lim['max_chargeback_rate']:.1%}"
        )

    def _pause(args: tuple[str, ...]) -> str:
        from core.crisis.response import (
            get_crisis_responder,
        )
        reason = (
            " ".join(args) if args else "owner via telegram"
        )
        get_crisis_responder().halt(reason=reason)
        return (
            "✗ Emergency halt engaged. "
            "Reply `resume` to clear."
        )

    def _resume(args: tuple[str, ...]) -> str:
        from core.crisis.response import (
            get_crisis_responder,
        )
        get_crisis_responder().resume()
        state = get_crisis_responder().detect_state()
        if state.halted:
            return (
                f"Manual halt cleared but still halted by: "
                f"{state.reason}"
            )
        return "✓ Crisis halt cleared."

    def _digest(args: tuple[str, ...]) -> str:
        from agents.owner_dialog.notify import notify_owner
        result = notify_owner(period_hours=24.0 * 7)
        if result.sent:
            return (
                f"📬 Digest sent "
                f"(message_id={result.message_id})"
            )
        return f"Could not send digest: {result.reason}"

    return {
        "approve": _approve,
        "approve_all": _approve_all,
        "reject": _reject,
        "reject_all": _reject_all,
        "status": _status,
        "limits": _limits,
        "pause": _pause,
        "resume": _resume,
        "digest": _digest,
    }
