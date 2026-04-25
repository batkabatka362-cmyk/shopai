"""Telegram Bot adapter — 2-way owner dialog channel.

Sprint 3 S3-5 (P1, LX.6 in docs/AGI_STACK.md). Closes the weekly-
digest approval loop: brain composes a digest → bot pushes it as a
markdown message → owner replies with ``approve 42`` / ``reject 42``
/ ``pause`` / ``status`` / ``limits`` → brain parses and acts.

Why Telegram: free, no payment required, bot API is public, owner
can chat from any device. No owner-facing UI to build on our side.

Credentials: ``TELEGRAM_BOT_TOKEN`` + ``TELEGRAM_CHAT_ID`` env vars
(or constructor args). Missing either → ``is_available()`` is False
and every send is a no-op that records a last_error.

API surface (intentionally narrow):

  * ``send_message(text, chat_id=None, parse_mode="Markdown")``
      → returns message_id on success, None on failure.
  * ``get_updates()`` → polls for new messages since the last
      offset; each update is a ``TelegramUpdate`` dataclass.
  * ``poll_commands()`` → thin wrapper that parses the first token
      of each incoming message into a ``TelegramCommand``.
  * ``stats()`` → last_error, sent / received counters, offset.

Idempotency: Telegram's ``sendMessage`` endpoint is *not* naturally
idempotent, but the brain only calls it once per decision so that's
acceptable. For ``get_updates`` we track the offset so the same
message is never processed twice.

Pure stdlib + requests. Thread-safe (Lock). LLM-free. Deterministic
given a fixed http client.
"""
from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from utils.logger import get_logger


logger = get_logger("core.adapters.telegram_bot")


_DEFAULT_TIMEOUT = 10.0
_DEFAULT_BASE_URL = "https://api.telegram.org"
_ENV_TOKEN = "TELEGRAM_BOT_TOKEN"
_ENV_CHAT_ID = "TELEGRAM_CHAT_ID"

# Commands the owner can send in chat. Ordering matters — first
# match wins, so longer prefixes should precede shorter ones that
# are a substring.
_KNOWN_COMMANDS: tuple[str, ...] = (
    "approve_all",
    "reject_all",
    "approve",
    "reject",
    "status",
    "limits",
    "pause",
    "resume",
    "digest",
    "help",
)


@dataclass
class TelegramUpdate:
    update_id: int
    chat_id: str
    text: str
    from_user: str = ""
    ts: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "update_id": self.update_id,
            "chat_id": self.chat_id,
            "text": self.text,
            "from_user": self.from_user,
            "ts": self.ts,
        }


@dataclass
class TelegramCommand:
    verb: str            # normalised command name, or "" if unknown
    args: tuple[str, ...] = ()
    update: TelegramUpdate | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "verb": self.verb,
            "args": list(self.args),
            "update": (
                self.update.as_dict() if self.update else None
            ),
        }


class TelegramBotAdapter:
    """Thin wrapper around Telegram's public bot API."""

    name = "telegram_bot"

    def __init__(
        self,
        *,
        token: str | None = None,
        chat_id: str | None = None,
        http: Any = None,
        timeout: float = _DEFAULT_TIMEOUT,
        base_url: str = _DEFAULT_BASE_URL,
    ) -> None:
        self._token = (
            token if token is not None
            else os.environ.get(_ENV_TOKEN, "")
        )
        self._chat_id = (
            chat_id if chat_id is not None
            else os.environ.get(_ENV_CHAT_ID, "")
        )
        self._http = http
        self._timeout = float(timeout)
        self._base = str(base_url).rstrip("/")
        self._lock = threading.Lock()
        self._offset = 0
        self._sent = 0
        self._received = 0
        self._last_error = ""

    def is_available(self) -> bool:
        return bool(self._token) and bool(self._chat_id)

    # ── URL helpers ──────────────────────────────────────

    def _url(self, method: str) -> str:
        return f"{self._base}/bot{self._token}/{method}"

    def _client(self) -> Any:
        if self._http is not None:
            return self._http
        import requests
        return requests

    # ── Send ─────────────────────────────────────────────

    def send_message(
        self,
        text: str,
        *,
        chat_id: str | None = None,
        parse_mode: str = "Markdown",
        disable_web_page_preview: bool = True,
    ) -> int | None:
        if not self.is_available():
            with self._lock:
                self._last_error = (
                    "not configured — set "
                    f"{_ENV_TOKEN} + {_ENV_CHAT_ID}"
                )
            return None
        if not text:
            with self._lock:
                self._last_error = "empty text"
            return None
        target = str(chat_id or self._chat_id)
        try:
            resp = self._client().post(
                self._url("sendMessage"),
                json={
                    "chat_id": target,
                    "text": text,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": (
                        disable_web_page_preview
                    ),
                },
                timeout=self._timeout,
            )
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._last_error = f"send exception: {exc}"
            logger.debug(
                "telegram sendMessage failed: %s", exc,
            )
            return None
        if resp.status_code >= 400:
            with self._lock:
                self._last_error = (
                    f"send HTTP {resp.status_code}: "
                    f"{(resp.text or '')[:120]}"
                )
            return None
        try:
            body = resp.json()
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._last_error = f"bad json: {exc}"
            return None
        if not body.get("ok"):
            with self._lock:
                self._last_error = (
                    "telegram rejected: "
                    + str(body.get("description", ""))
                )
            return None
        msg_id = int(
            body.get("result", {}).get("message_id", 0) or 0,
        )
        with self._lock:
            self._sent += 1
            self._last_error = ""
        return msg_id or None

    # ── Poll ─────────────────────────────────────────────

    def get_updates(
        self, *, limit: int = 20,
    ) -> list[TelegramUpdate]:
        if not self.is_available():
            with self._lock:
                self._last_error = "not configured"
            return []
        try:
            resp = self._client().get(
                self._url("getUpdates"),
                params={
                    "offset": self._offset,
                    "limit": int(limit),
                    "timeout": 0,
                },
                timeout=self._timeout,
            )
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._last_error = f"poll exception: {exc}"
            logger.debug(
                "telegram getUpdates failed: %s", exc,
            )
            return []
        if resp.status_code >= 400:
            with self._lock:
                self._last_error = (
                    f"poll HTTP {resp.status_code}"
                )
            return []
        try:
            body = resp.json()
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._last_error = f"bad json: {exc}"
            return []
        if not body.get("ok"):
            with self._lock:
                self._last_error = (
                    "telegram rejected: "
                    + str(body.get("description", ""))
                )
            return []
        raw_updates = body.get("result") or []
        out: list[TelegramUpdate] = []
        max_uid = self._offset
        for upd in raw_updates:
            uid = int(upd.get("update_id") or 0)
            if uid <= 0:
                continue
            msg = upd.get("message") or upd.get(
                "edited_message",
            ) or {}
            chat = msg.get("chat") or {}
            user = msg.get("from") or {}
            text = str(msg.get("text") or "")
            if not text:
                continue
            out.append(TelegramUpdate(
                update_id=uid,
                chat_id=str(chat.get("id", "")),
                text=text,
                from_user=str(
                    user.get("username")
                    or user.get("id", ""),
                ),
                ts=float(msg.get("date") or time.time()),
            ))
            if uid > max_uid:
                max_uid = uid
        if out:
            # Advance offset past the highest-seen update_id so
            # Telegram's server-side ack drops them.
            with self._lock:
                self._offset = max_uid + 1
                self._received += len(out)
                self._last_error = ""
        return out

    def poll_commands(
        self, *, limit: int = 20,
    ) -> list[TelegramCommand]:
        """Convenience: ``get_updates`` + command parsing.

        Only messages whose chat_id matches the configured
        ``TELEGRAM_CHAT_ID`` are returned so random inbound
        strangers can't issue commands.
        """
        updates = self.get_updates(limit=limit)
        cmds: list[TelegramCommand] = []
        for upd in updates:
            if (
                self._chat_id
                and str(upd.chat_id) != str(self._chat_id)
            ):
                continue
            verb, args = parse_command(upd.text)
            cmds.append(TelegramCommand(
                verb=verb, args=args, update=upd,
            ))
        return cmds

    # ── Stats ────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "adapter": self.name,
                "configured": bool(
                    self._token and self._chat_id,
                ),
                "offset": self._offset,
                "sent": self._sent,
                "received": self._received,
                "last_error": self._last_error,
            }


# ── Command parser ──────────────────────────────────────────


def parse_command(text: str) -> tuple[str, tuple[str, ...]]:
    """Parse an incoming message into (verb, args).

    Leading ``/`` and ``@<botname>`` suffix are stripped; unknown
    verbs collapse to empty string so callers can distinguish
    "unrecognised command" from "status query" without a lookup.
    """
    raw = (text or "").strip()
    if not raw:
        return "", ()
    # Drop leading slash + optional @botname suffix on first token
    tokens = re.split(r"\s+", raw, maxsplit=10)
    head = tokens[0].lstrip("/").lower()
    head = head.split("@", 1)[0]
    for cmd in _KNOWN_COMMANDS:
        if head == cmd:
            return cmd, tuple(tokens[1:])
    return "", tuple(tokens)
