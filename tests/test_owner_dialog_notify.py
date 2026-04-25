"""Tests for agents.owner_dialog.notify."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from agents.owner_dialog.notify import notify_owner, NotifyResult


def _fake_digest(text_markdown: str = "*hello*"):
    d = MagicMock()
    d.as_markdown.return_value = text_markdown
    return d


def _compose_fn_that_returns(digest):
    return lambda period_hours: digest


class TestNotifyOwner(unittest.TestCase):
    def test_dry_run_does_not_send(self):
        digest = _fake_digest("*dry preview*")
        bot = MagicMock()
        result = notify_owner(
            compose_fn=_compose_fn_that_returns(digest),
            bot=bot,
            dry_run=True,
        )
        self.assertFalse(result.sent)
        self.assertEqual(result.reason, "dry_run")
        self.assertIn("dry preview", result.text)
        bot.send_message.assert_not_called()

    def test_bot_unavailable(self):
        digest = _fake_digest()
        bot = MagicMock()
        bot.is_available.return_value = False
        result = notify_owner(
            compose_fn=_compose_fn_that_returns(digest),
            bot=bot,
        )
        self.assertFalse(result.sent)
        self.assertIn("not configured", result.reason)

    def test_happy_path_sends(self):
        digest = _fake_digest("*digest body*")
        bot = MagicMock()
        bot.is_available.return_value = True
        bot.send_message.return_value = 555
        result = notify_owner(
            compose_fn=_compose_fn_that_returns(digest),
            bot=bot,
        )
        self.assertTrue(result.sent)
        self.assertEqual(result.message_id, 555)
        args, kwargs = bot.send_message.call_args
        self.assertEqual(args[0], "*digest body*")

    def test_send_failure_surfaces_error(self):
        digest = _fake_digest()
        bot = MagicMock()
        bot.is_available.return_value = True
        bot.send_message.return_value = None
        bot.stats.return_value = {
            "last_error": "chat_not_found",
        }
        result = notify_owner(
            compose_fn=_compose_fn_that_returns(digest),
            bot=bot,
        )
        self.assertFalse(result.sent)
        self.assertIn("chat_not_found", result.reason)

    def test_compose_exception_degrades(self):
        def boom(period_hours):
            raise RuntimeError("digest build failed")

        result = notify_owner(compose_fn=boom, bot=MagicMock())
        self.assertFalse(result.sent)
        self.assertIn(
            "compose failed", result.reason,
        )

    def test_explicit_chat_id_forwarded(self):
        digest = _fake_digest()
        bot = MagicMock()
        bot.is_available.return_value = True
        bot.send_message.return_value = 1
        notify_owner(
            compose_fn=_compose_fn_that_returns(digest),
            bot=bot,
            chat_id="7",
        )
        _, kwargs = bot.send_message.call_args
        self.assertEqual(kwargs["chat_id"], "7")


class TestResultDict(unittest.TestCase):
    def test_as_dict(self):
        r = NotifyResult(sent=True, message_id=1, text="x")
        d = r.as_dict()
        self.assertTrue(d["sent"])
        self.assertEqual(d["message_id"], 1)
        self.assertEqual(d["text"], "x")


if __name__ == "__main__":
    unittest.main()
