"""Cycle-error digest — scan autopilot log + push to Telegram.

``shopai notify`` already sends a launch digest; this module
ships the complementary "something broke overnight" digest.
It reads the autopilot cycle log, filters to cycles with
non-empty ``error``, and composes a short markdown summary:

    🚨 ShopAI autopilot — 3 errors in last 24h

    Last 24h: 12 cycles, 3 with errors.

    • #42 03:15 — autopilot raised: ConnectionError: Shopify …
    • #38 01:55 — distill raised: sqlite busy_timeout …
    • #35 00:48 — autopilot raised: Meta API 502 …

    Run `shopai cycles --limit 50` for the full picture.

Sends via core.adapters.telegram_bot.TelegramBotAdapter. The
token + chat id come from the standard env pair; a missing
config surfaces as a ``ErrorDigestResult`` with
``sent=False`` and a fix hint so tests + CLI + MCP all get
the same failure shape.

Pure stdlib + dependency-injected adapter. Thread-safe (no
state).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ErrorDigestResult:
    """Structured outcome of :func:`send_error_digest`."""

    sent: bool
    dry_run: bool
    cycles_scanned: int
    errors_found: int
    message_id: int | None = None
    text: str = ""
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "sent": self.sent,
            "dry_run": self.dry_run,
            "cycles_scanned": self.cycles_scanned,
            "errors_found": self.errors_found,
            "message_id": self.message_id,
            "text": self.text,
            "reason": self.reason,
        }


def _read_tail(
    log_path: Path, *, limit: int,
) -> list[dict[str, Any]]:
    """Read up to ``limit`` most-recent cycle rows from the
    log. Malformed lines are skipped silently."""
    if not log_path.exists():
        return []
    try:
        lines = log_path.read_text().splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            rows.append(parsed)
    # Tail
    return rows[-int(limit):] if limit > 0 else rows


def _filter_errors(
    rows: list[dict[str, Any]], *, hours: float,
    now_fn: Any,
) -> list[dict[str, Any]]:
    cutoff = float(now_fn()) - (
        float(hours) * 3600.0
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        ts = float(row.get("ts", 0) or 0)
        err = str(row.get("error", "") or "")
        if not err:
            continue
        if ts and ts < cutoff:
            continue
        out.append(row)
    return out


def _format_message(
    errors: list[dict[str, Any]],
    *,
    cycles_scanned: int,
    hours: float,
) -> str:
    if not errors:
        return (
            f"✅ ShopAI autopilot — no errors in last "
            f"{int(hours)}h ({cycles_scanned} cycles)."
        )
    lines: list[str] = []
    lines.append(
        f"🚨 *ShopAI autopilot* — {len(errors)} "
        f"errors in last {int(hours)}h"
    )
    lines.append("")
    lines.append(
        f"{cycles_scanned} cycles, "
        f"{len(errors)} with errors."
    )
    lines.append("")
    for row in errors[-10:]:  # last 10 at most
        ts_s = time.strftime(
            "%H:%M",
            time.localtime(
                float(row.get("ts", 0) or 0),
            ),
        )
        cyc = row.get("cycle", "?")
        err = str(row.get("error", ""))[:80]
        lines.append(
            f"• #{cyc} {ts_s} — {err}",
        )
    lines.append("")
    lines.append(
        "_Run `shopai cycles --limit 50` for details._",
    )
    return "\n".join(lines)


def send_error_digest(
    *,
    log_path: str = "data/autopilot_loop.log",
    hours: float = 24.0,
    scan_limit: int = 500,
    dry_run: bool = False,
    chat_id: str | None = None,
    adapter: Any = None,
    now_fn: Any = None,
) -> ErrorDigestResult:
    """Scan the cycle log + push an error digest to Telegram.

    Returns a structured :class:`ErrorDigestResult` — callers
    (CLI + MCP) share the same success/failure payload shape.
    When no errors are in-window, a green "all clear" message
    is still composed so the owner gets a heartbeat rather
    than silence; callers can skip sending via
    ``dry_run=True`` if they only want the clear signal.
    """
    now = now_fn or time.time
    rows = _read_tail(
        Path(log_path), limit=scan_limit,
    )
    errors = _filter_errors(
        rows, hours=hours, now_fn=now,
    )
    text = _format_message(
        errors,
        cycles_scanned=len(rows),
        hours=hours,
    )
    if dry_run:
        return ErrorDigestResult(
            sent=False,
            dry_run=True,
            cycles_scanned=len(rows),
            errors_found=len(errors),
            text=text,
            reason="dry_run",
        )
    # Resolve adapter
    if adapter is None:
        try:
            from core.adapters.telegram_bot import (
                TelegramBotAdapter,
            )
            adapter = TelegramBotAdapter()
        except Exception as exc:  # noqa: BLE001
            return ErrorDigestResult(
                sent=False,
                dry_run=False,
                cycles_scanned=len(rows),
                errors_found=len(errors),
                text=text,
                reason=(
                    f"telegram adapter unavailable: "
                    f"{exc}"
                ),
            )
    if not getattr(adapter, "is_available", lambda: False)():
        return ErrorDigestResult(
            sent=False,
            dry_run=False,
            cycles_scanned=len(rows),
            errors_found=len(errors),
            text=text,
            reason=(
                "telegram not configured — set "
                "TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID"
            ),
        )
    try:
        message_id = adapter.send_message(
            text, chat_id=chat_id,
        )
    except Exception as exc:  # noqa: BLE001
        return ErrorDigestResult(
            sent=False,
            dry_run=False,
            cycles_scanned=len(rows),
            errors_found=len(errors),
            text=text,
            reason=f"send raised: {exc}",
        )
    if message_id is None:
        return ErrorDigestResult(
            sent=False,
            dry_run=False,
            cycles_scanned=len(rows),
            errors_found=len(errors),
            text=text,
            reason="send returned None",
        )
    return ErrorDigestResult(
        sent=True,
        dry_run=False,
        cycles_scanned=len(rows),
        errors_found=len(errors),
        message_id=int(message_id),
        text=text,
        reason="",
    )
