"""Tests for core.adapters.telegram_bot.bot."""
from __future__ import annotations

import json
import os
import unittest
from unittest.mock import MagicMock

from core.adapters.telegram_bot.bot import (
    TelegramBotAdapter,
    TelegramUpdate,
    TelegramCommand,
    parse_command,
)


def _http_response(status=200, payload=None):
    r = MagicMock()
    r.status_code = status
    r.text = json.dumps(payload or {})
    r.json.return_value = payload or {}
    return r


class TestConfig(unittest.TestCase):
    def test_unavailable_without_credentials(self):
        bot = TelegramBotAdapter(token="", chat_id="")
        self.assertFalse(bot.is_available())

    def test_env_pickup(self):
        os.environ["TELEGRAM_BOT_TOKEN"] = "t1"
        os.environ["TELEGRAM_CHAT_ID"] = "42"
        try:
            bot = TelegramBotAdapter()
            self.assertTrue(bot.is_available())
        finally:
            os.environ.pop("TELEGRAM_BOT_TOKEN", None)
            os.environ.pop("TELEGRAM_CHAT_ID", None)

    def test_explicit_args_override_env(self):
        os.environ["TELEGRAM_BOT_TOKEN"] = "env"
        try:
            bot = TelegramBotAdapter(
                token="explicit", chat_id="99",
            )
            self.assertTrue(bot.is_available())
        finally:
            os.environ.pop("TELEGRAM_BOT_TOKEN", None)


class TestSendMessage(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        self.bot = TelegramBotAdapter(
            token="tok", chat_id="42",
            http=self.client,
        )

    def test_send_ok_returns_message_id(self):
        self.client.post.return_value = _http_response(
            200,
            payload={
                "ok": True,
                "result": {"message_id": 101},
            },
        )
        mid = self.bot.send_message("hello")
        self.assertEqual(mid, 101)
        self.assertEqual(self.bot.stats()["sent"], 1)

    def test_send_empty_text_noop(self):
        self.assertIsNone(self.bot.send_message(""))
        self.assertIn(
            "empty text",
            self.bot.stats()["last_error"],
        )
        self.client.post.assert_not_called()

    def test_send_not_configured(self):
        bot = TelegramBotAdapter(token="", chat_id="")
        self.assertIsNone(bot.send_message("hi"))
        self.assertIn(
            "not configured", bot.stats()["last_error"],
        )

    def test_http_error_surfaces(self):
        r = MagicMock()
        r.status_code = 500
        r.text = "boom"
        self.client.post.return_value = r
        self.assertIsNone(self.bot.send_message("hi"))
        self.assertIn(
            "500", self.bot.stats()["last_error"],
        )

    def test_api_rejection_surfaces(self):
        self.client.post.return_value = _http_response(
            200,
            payload={
                "ok": False,
                "description": "chat not found",
            },
        )
        self.assertIsNone(self.bot.send_message("hi"))
        self.assertIn(
            "chat not found",
            self.bot.stats()["last_error"],
        )

    def test_exception_caught(self):
        self.client.post.side_effect = RuntimeError("net down")
        self.assertIsNone(self.bot.send_message("hi"))
        self.assertIn(
            "net down", self.bot.stats()["last_error"],
        )

    def test_send_respects_explicit_chat_id(self):
        self.client.post.return_value = _http_response(
            200,
            payload={
                "ok": True,
                "result": {"message_id": 1},
            },
        )
        self.bot.send_message("x", chat_id="99")
        args, kwargs = self.client.post.call_args
        self.assertEqual(
            kwargs["json"]["chat_id"], "99",
        )


class TestPoll(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        self.bot = TelegramBotAdapter(
            token="tok", chat_id="42",
            http=self.client,
        )

    def _updates(self, *items):
        return _http_response(
            200,
            payload={"ok": True, "result": list(items)},
        )

    def test_parses_messages(self):
        self.client.get.return_value = self._updates(
            {
                "update_id": 10,
                "message": {
                    "chat": {"id": 42},
                    "from": {
                        "username": "owner",
                        "id": 1,
                    },
                    "text": "status",
                    "date": 1_700_000_000,
                },
            },
            {
                "update_id": 11,
                "message": {
                    "chat": {"id": 42},
                    "text": "approve 7",
                    "date": 1_700_000_001,
                },
            },
        )
        out = self.bot.get_updates()
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0].update_id, 10)
        self.assertEqual(out[0].text, "status")
        self.assertEqual(out[0].from_user, "owner")
        self.assertEqual(
            self.bot.stats()["offset"], 12,
        )

    def test_offset_advances(self):
        self.client.get.return_value = self._updates(
            {
                "update_id": 20,
                "message": {
                    "chat": {"id": 42},
                    "text": "a",
                },
            },
        )
        self.bot.get_updates()
        self.client.get.return_value = self._updates()
        self.bot.get_updates()
        args, kwargs = self.client.get.call_args
        self.assertEqual(kwargs["params"]["offset"], 21)

    def test_ignores_non_text_messages(self):
        self.client.get.return_value = self._updates(
            {
                "update_id": 5,
                "message": {
                    "chat": {"id": 42},
                    # no text
                },
            },
        )
        self.assertEqual(self.bot.get_updates(), [])

    def test_http_error_returns_empty(self):
        r = MagicMock()
        r.status_code = 429
        r.text = "rate"
        r.json.return_value = {}
        self.client.get.return_value = r
        self.assertEqual(self.bot.get_updates(), [])
        self.assertIn(
            "429", self.bot.stats()["last_error"],
        )

    def test_poll_commands_filters_by_chat_id(self):
        self.client.get.return_value = self._updates(
            {
                "update_id": 30,
                "message": {
                    "chat": {"id": 42},   # match
                    "text": "approve 5",
                },
            },
            {
                "update_id": 31,
                "message": {
                    "chat": {"id": 999},   # stranger
                    "text": "approve 6",
                },
            },
        )
        cmds = self.bot.poll_commands()
        self.assertEqual(len(cmds), 1)
        self.assertEqual(cmds[0].verb, "approve")
        self.assertEqual(cmds[0].args, ("5",))


class TestParseCommand(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(parse_command(""), ("", ()))

    def test_slash_stripped(self):
        verb, args = parse_command("/status")
        self.assertEqual(verb, "status")

    def test_at_botname_stripped(self):
        verb, _ = parse_command("/approve@shopai_bot 42")
        self.assertEqual(verb, "approve")

    def test_approve_with_id(self):
        verb, args = parse_command("approve launch_7")
        self.assertEqual(verb, "approve")
        self.assertEqual(args, ("launch_7",))

    def test_approve_all_match(self):
        verb, _ = parse_command("approve_all")
        self.assertEqual(verb, "approve_all")

    def test_unknown_returns_blank_verb(self):
        verb, args = parse_command("delete everything")
        self.assertEqual(verb, "")
        self.assertEqual(args[0], "delete")

    def test_case_insensitive(self):
        verb, _ = parse_command("STATUS")
        self.assertEqual(verb, "status")

    def test_known_command_preserves_arg_case(self):
        verb, args = parse_command("approve Launch_X")
        self.assertEqual(verb, "approve")
        self.assertEqual(args, ("Launch_X",))


class TestStats(unittest.TestCase):
    def test_stats_shape(self):
        bot = TelegramBotAdapter(token="t", chat_id="c")
        s = bot.stats()
        self.assertTrue(s["configured"])
        self.assertEqual(s["offset"], 0)
        self.assertEqual(s["sent"], 0)
        self.assertEqual(s["received"], 0)


if __name__ == "__main__":
    unittest.main()
