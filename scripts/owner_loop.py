"""Owner loop daemon — poll Telegram + push digests on a cadence.

Wire-in #5/5. Closes the last gap in the autonomous loop: the
owner's two-way dialog channel now runs unattended.

Two independent cadences:

  * ``--poll-interval`` (default 60s) — pulls new Telegram
    commands via OwnerDialogDispatcher and dispatches them to
    brain handlers (approve / reject / status / limits / pause /
    resume / digest / help).
  * ``--digest-interval`` (default 24h) — composes the weekly
    launch digest via ``notify_owner`` and pushes it to the
    configured chat.

Exits cleanly on SIGINT / SIGTERM. Writes one JSON line per
dispatch or digest push to ``data/owner_loop.log`` so owners can
diff what happened while they were asleep.

Safe to run when Telegram env vars are missing: the bot adapter's
``is_available()`` returns False, each tick is a no-op, and the
log records ``status=skipped``. This lets the systemd unit stay
active across credential rotations.

Usage:
    python scripts/owner_loop.py                        # defaults
    python scripts/owner_loop.py --poll-interval 30     # tighter poll
    python scripts/owner_loop.py --digest-interval 0    # disable digest
    python scripts/owner_loop.py --iterations 3         # run 3 ticks

Pure stdlib + injection-friendly. Deterministic under a fixed
``now_fn`` for tests.
"""
from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if __name__ == "__main__":
    _ROOT = Path(__file__).resolve().parent.parent
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from utils.logger import get_logger


logger = get_logger("scripts.owner_loop")


_DEFAULT_POLL_INTERVAL_S = 60.0
_DEFAULT_DIGEST_INTERVAL_S = 24 * 3600.0
_DEFAULT_DIGEST_HOURS = 24.0 * 7
_DEFAULT_LOG_PATH = Path("data/owner_loop.log")


@dataclass
class OwnerLoopConfig:
    poll_interval_s: float = _DEFAULT_POLL_INTERVAL_S
    digest_interval_s: float = _DEFAULT_DIGEST_INTERVAL_S
    digest_period_hours: float = _DEFAULT_DIGEST_HOURS
    max_iterations: int = 0        # 0 = infinite
    poll_limit: int = 20
    log_path: str = str(_DEFAULT_LOG_PATH)
    quiet: bool = False

    def __post_init__(self) -> None:
        if self.poll_interval_s <= 0:
            raise ValueError(
                "poll_interval_s must be > 0",
            )
        if self.digest_interval_s < 0:
            raise ValueError(
                "digest_interval_s must be ≥ 0",
            )
        if self.max_iterations < 0:
            raise ValueError(
                "max_iterations must be ≥ 0",
            )


@dataclass
class TickSummary:
    tick: int
    ts: float
    poll_ran: bool = False
    poll_dispatched: int = 0
    poll_errors: int = 0
    digest_ran: bool = False
    digest_sent: bool = False
    digest_reason: str = ""
    duration_s: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "tick": self.tick,
            "poll_ran": self.poll_ran,
            "poll_dispatched": self.poll_dispatched,
            "poll_errors": self.poll_errors,
            "digest_ran": self.digest_ran,
            "digest_sent": self.digest_sent,
            "digest_reason": self.digest_reason,
            "duration_s": round(self.duration_s, 3),
        }


class OwnerLoop:
    """Daemon that polls Telegram and pushes digests on cadence."""

    def __init__(
        self,
        config: OwnerLoopConfig,
        *,
        dispatcher: Any = None,
        notifier: Any = None,
        bot: Any = None,
        now_fn: Any = None,
        sleep_fn: Any = None,
    ) -> None:
        self._config = config
        self._dispatcher = dispatcher
        self._notifier = notifier
        self._bot = bot
        self._now_fn = now_fn or time.time
        self._sleep_fn = sleep_fn or time.sleep
        self._tick = 0
        self._last_digest_ts = 0.0
        self._stop = False
        self._log_path = Path(config.log_path)
        self._log_path.parent.mkdir(
            parents=True, exist_ok=True,
        )

    # ── Dependencies ─────────────────────────────────────

    def _get_bot(self) -> Any:
        if self._bot is not None:
            return self._bot
        from core.adapters.telegram_bot import (
            TelegramBotAdapter,
        )
        self._bot = TelegramBotAdapter()
        return self._bot

    def _get_dispatcher(self) -> Any:
        if self._dispatcher is not None:
            return self._dispatcher
        from agents.owner_dialog.dispatcher import (
            OwnerDialogDispatcher,
            build_default_handlers,
        )
        self._dispatcher = OwnerDialogDispatcher(
            bot=self._get_bot(),
            handlers=build_default_handlers(),
        )
        return self._dispatcher

    def _get_notifier(self) -> Any:
        if self._notifier is not None:
            return self._notifier
        from agents.owner_dialog.notify import notify_owner
        self._notifier = notify_owner
        return self._notifier

    # ── Control ──────────────────────────────────────────

    def stop(self) -> None:
        self._stop = True

    def should_stop(self) -> bool:
        if self._stop:
            return True
        if (
            self._config.max_iterations > 0
            and self._tick >= self._config.max_iterations
        ):
            return True
        return False

    # ── Tick ─────────────────────────────────────────────

    def tick(self) -> TickSummary:
        started = float(self._now_fn())
        self._tick += 1
        summary = TickSummary(
            tick=self._tick, ts=started,
        )
        # Poll commands
        try:
            bot = self._get_bot()
            if bot.is_available():
                dispatcher = self._get_dispatcher()
                results = dispatcher.poll_and_dispatch(
                    limit=self._config.poll_limit,
                )
                summary.poll_ran = True
                summary.poll_dispatched = len(results)
                summary.poll_errors = sum(
                    1 for r in results if not r.ok
                )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "poll tick failed: %s", exc,
            )
            summary.poll_errors += 1
        # Digest push on cadence. On first tick (last_digest_ts
        # is still 0.0) fire immediately instead of making the
        # owner wait ``interval`` seconds.
        interval = self._config.digest_interval_s
        if interval > 0:
            now = float(self._now_fn())
            elapsed = now - self._last_digest_ts
            if self._last_digest_ts <= 0 or elapsed >= interval:
                try:
                    notifier = self._get_notifier()
                    result = notifier(
                        period_hours=(
                            self._config.digest_period_hours
                        ),
                    )
                    summary.digest_ran = True
                    summary.digest_sent = bool(result.sent)
                    summary.digest_reason = (
                        "" if result.sent
                        else (result.reason or "")
                    )
                    self._last_digest_ts = float(
                        self._now_fn(),
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        "digest tick failed: %s", exc,
                    )
                    summary.digest_ran = True
                    summary.digest_sent = False
                    summary.digest_reason = str(exc)
        summary.duration_s = (
            float(self._now_fn()) - started
        )
        self._write_log(summary)
        return summary

    def run(self) -> list[TickSummary]:
        """Run until ``should_stop`` returns True."""
        summaries: list[TickSummary] = []
        while not self.should_stop():
            summary = self.tick()
            summaries.append(summary)
            if self._stop or self.should_stop():
                break
            self._sleep_fn(self._config.poll_interval_s)
        return summaries

    # ── Log ──────────────────────────────────────────────

    def _write_log(self, summary: TickSummary) -> None:
        try:
            line = json.dumps(summary.as_dict())
            with self._log_path.open("a") as fh:
                fh.write(line + "\n")
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "owner_loop log write failed: %s", exc,
            )


# ── Entry point ─────────────────────────────────────────────


def _parse_args(argv: list[str] | None = None) -> Any:
    p = argparse.ArgumentParser(
        description=(
            "ShopAI owner loop — poll Telegram + push "
            "digests on a cadence."
        ),
    )
    p.add_argument(
        "--poll-interval", type=float,
        default=_DEFAULT_POLL_INTERVAL_S,
        help=(
            "Seconds between Telegram polls "
            f"(default {int(_DEFAULT_POLL_INTERVAL_S)})"
        ),
    )
    p.add_argument(
        "--digest-interval", type=float,
        default=_DEFAULT_DIGEST_INTERVAL_S,
        help=(
            "Seconds between digest pushes "
            f"(default 24h = {int(_DEFAULT_DIGEST_INTERVAL_S)}). "
            "0 disables digests."
        ),
    )
    p.add_argument(
        "--digest-hours", type=float,
        default=_DEFAULT_DIGEST_HOURS,
        help=(
            "Lookback window for each digest "
            "(default 168 = 7d)"
        ),
    )
    p.add_argument(
        "--iterations", type=int, default=0,
        help="0 = run forever (default)",
    )
    p.add_argument(
        "--poll-limit", type=int, default=20,
    )
    p.add_argument(
        "--log-path", default=str(_DEFAULT_LOG_PATH),
    )
    p.add_argument(
        "--quiet", action="store_true",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        config = OwnerLoopConfig(
            poll_interval_s=float(args.poll_interval),
            digest_interval_s=float(args.digest_interval),
            digest_period_hours=float(args.digest_hours),
            max_iterations=int(args.iterations),
            poll_limit=int(args.poll_limit),
            log_path=args.log_path,
            quiet=bool(args.quiet),
        )
    except ValueError as exc:
        print(f"[config] {exc}", file=sys.stderr)
        return 2
    loop = OwnerLoop(config)

    def _handle_stop(signum, frame):
        loop.stop()

    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)
    try:
        summaries = loop.run()
    except KeyboardInterrupt:
        loop.stop()
        summaries = []
    if not args.quiet:
        print(
            f"Owner loop exited after {len(summaries)} "
            f"tick(s). Log: {config.log_path}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
