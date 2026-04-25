"""Tests for scripts.owner_loop — Wire-in #5 daemon."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from scripts.owner_loop import (
    OwnerLoop,
    OwnerLoopConfig,
    TickSummary,
)


def _config(tmp, **overrides):
    kw = dict(
        poll_interval_s=60.0,
        digest_interval_s=3600.0,
        log_path=str(Path(tmp) / "owner_loop.log"),
    )
    kw.update(overrides)
    return OwnerLoopConfig(**kw)


def _loop(
    tmp, *, bot=None, dispatcher=None, notifier=None,
    now_list=None, **cfg_overrides,
):
    cfg = _config(tmp, **cfg_overrides)
    now_iter = iter(
        now_list if now_list is not None else [
            1000.0, 1000.5, 1001.0, 2000.0, 2000.5,
        ]
    )
    now_fn = lambda: next(
        now_iter, 9999.0,
    )
    return OwnerLoop(
        cfg,
        bot=bot, dispatcher=dispatcher,
        notifier=notifier,
        now_fn=now_fn,
        sleep_fn=lambda s: None,
    )


class TestConfig(unittest.TestCase):
    def test_negative_poll_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                _config(tmp, poll_interval_s=0)

    def test_negative_digest_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                _config(tmp, digest_interval_s=-1)

    def test_negative_iterations_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                _config(tmp, max_iterations=-1)


class TestTick(unittest.TestCase):
    def test_unavailable_bot_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot = MagicMock()
            bot.is_available.return_value = False
            loop = _loop(
                tmp,
                bot=bot,
                digest_interval_s=0,   # disable digest
            )
            summary = loop.tick()
            self.assertFalse(summary.poll_ran)
            self.assertEqual(summary.poll_dispatched, 0)

    def test_available_bot_polls(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot = MagicMock()
            bot.is_available.return_value = True
            dispatcher = MagicMock()
            dispatcher.poll_and_dispatch.return_value = [
                MagicMock(ok=True),
                MagicMock(ok=False),
            ]
            loop = _loop(
                tmp,
                bot=bot, dispatcher=dispatcher,
                digest_interval_s=0,
            )
            summary = loop.tick()
            self.assertTrue(summary.poll_ran)
            self.assertEqual(summary.poll_dispatched, 2)
            self.assertEqual(summary.poll_errors, 1)

    def test_digest_fires_on_first_tick(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot = MagicMock()
            bot.is_available.return_value = False
            notifier = MagicMock()
            notifier.return_value = MagicMock(
                sent=True,
                reason="",
                message_id=5,
            )
            loop = _loop(
                tmp,
                bot=bot, notifier=notifier,
                digest_interval_s=3600.0,
            )
            summary = loop.tick()
            self.assertTrue(summary.digest_ran)
            self.assertTrue(summary.digest_sent)
            notifier.assert_called_once()

    def test_digest_respects_interval(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot = MagicMock()
            bot.is_available.return_value = False
            notifier = MagicMock()
            notifier.return_value = MagicMock(
                sent=True,
                reason="",
                message_id=5,
            )
            # Now_fn: first tick at t=1000 (digest fires,
            # sets last=1000), second at t=1500 (interval
            # 3600, elapsed=500 → not fired), third at
            # t=5000 (elapsed=4000 → fired).
            now_iter = iter([
                1000.0, 1000.1,   # tick 1
                1500.0, 1500.1,   # tick 2 (no digest)
                5000.0, 5000.1,   # tick 3 (digest)
            ])
            cfg = _config(
                tmp, digest_interval_s=3600.0,
            )
            loop = OwnerLoop(
                cfg,
                bot=bot, notifier=notifier,
                now_fn=lambda: next(now_iter, 9999.0),
                sleep_fn=lambda s: None,
            )
            loop.tick()   # fires
            loop.tick()   # skips
            loop.tick()   # fires
            self.assertEqual(notifier.call_count, 2)

    def test_digest_disabled_when_interval_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot = MagicMock()
            bot.is_available.return_value = False
            notifier = MagicMock()
            loop = _loop(
                tmp,
                bot=bot, notifier=notifier,
                digest_interval_s=0,
            )
            loop.tick()
            notifier.assert_not_called()

    def test_notifier_exception_captured(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot = MagicMock()
            bot.is_available.return_value = False
            notifier = MagicMock(
                side_effect=RuntimeError("net down"),
            )
            loop = _loop(
                tmp,
                bot=bot, notifier=notifier,
                digest_interval_s=3600.0,
            )
            summary = loop.tick()
            self.assertTrue(summary.digest_ran)
            self.assertFalse(summary.digest_sent)
            self.assertIn(
                "net down", summary.digest_reason,
            )


class TestRunLoop(unittest.TestCase):
    def test_honors_max_iterations(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot = MagicMock()
            bot.is_available.return_value = False
            loop = _loop(
                tmp,
                bot=bot,
                digest_interval_s=0,
                max_iterations=3,
            )
            summaries = loop.run()
            self.assertEqual(len(summaries), 3)

    def test_stop_interrupts_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot = MagicMock()
            bot.is_available.return_value = False
            loop = _loop(
                tmp,
                bot=bot,
                digest_interval_s=0,
                max_iterations=100,
            )
            loop.stop()
            summaries = loop.run()
            self.assertEqual(summaries, [])

    def test_log_file_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot = MagicMock()
            bot.is_available.return_value = False
            loop = _loop(
                tmp,
                bot=bot,
                digest_interval_s=0,
                max_iterations=2,
            )
            loop.run()
            log_path = (
                Path(tmp) / "owner_loop.log"
            )
            self.assertTrue(log_path.exists())
            lines = log_path.read_text().strip().split("\n")
            self.assertEqual(len(lines), 2)


class TestTickDict(unittest.TestCase):
    def test_tick_summary_dict(self):
        s = TickSummary(tick=1, ts=100.0)
        d = s.as_dict()
        self.assertEqual(d["tick"], 1)
        self.assertIn("poll_dispatched", d)


if __name__ == "__main__":
    unittest.main()
