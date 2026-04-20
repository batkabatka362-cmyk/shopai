"""Tests for agents.owner_dialog.dispatcher."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from agents.owner_dialog.dispatcher import (
    DispatchResult,
    OwnerDialogDispatcher,
    build_default_handlers,
)


def _fake_bot(commands=None, send_id=7, available=True):
    bot = MagicMock()
    bot.is_available.return_value = available
    bot.poll_commands.return_value = commands or []
    bot.send_message.return_value = send_id
    return bot


def _cmd(verb, *args, update_id=1, chat_id="42"):
    cmd = MagicMock()
    cmd.verb = verb
    cmd.args = tuple(args)
    upd = MagicMock()
    upd.update_id = update_id
    upd.chat_id = chat_id
    upd.text = f"{verb} " + " ".join(args)
    cmd.update = upd
    return cmd


class TestInit(unittest.TestCase):
    def test_requires_bot(self):
        with self.assertRaises(ValueError):
            OwnerDialogDispatcher(bot=None)

    def test_register_bad_verb(self):
        d = OwnerDialogDispatcher(bot=_fake_bot())
        with self.assertRaises(ValueError):
            d.register("", lambda args: "x")


class TestDispatch(unittest.TestCase):
    def test_unavailable_bot_returns_empty(self):
        d = OwnerDialogDispatcher(
            bot=_fake_bot(available=False),
        )
        self.assertEqual(d.poll_and_dispatch(), [])

    def test_help_verb_always_works(self):
        bot = _fake_bot(commands=[_cmd("help")])
        d = OwnerDialogDispatcher(bot=bot)
        results = d.poll_and_dispatch()
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].ok)
        self.assertIn(
            "ShopAI commands", results[0].reply,
        )
        bot.send_message.assert_called_once()

    def test_unknown_verb_returns_error_reply(self):
        bot = _fake_bot(commands=[_cmd("")])
        d = OwnerDialogDispatcher(bot=bot)
        results = d.poll_and_dispatch()
        self.assertFalse(results[0].ok)
        self.assertIn(
            "Unknown command", results[0].reply,
        )

    def test_no_handler_registered_returns_error(self):
        bot = _fake_bot(commands=[_cmd("approve", "5")])
        d = OwnerDialogDispatcher(bot=bot, handlers={})
        results = d.poll_and_dispatch()
        self.assertFalse(results[0].ok)
        self.assertIn("No handler", results[0].reply)

    def test_custom_handler_returns_reply(self):
        bot = _fake_bot(commands=[_cmd("approve", "42")])
        d = OwnerDialogDispatcher(
            bot=bot,
            handlers={
                "approve": lambda args: f"OK {args[0]}",
            },
        )
        results = d.poll_and_dispatch()
        self.assertTrue(results[0].ok)
        self.assertEqual(results[0].reply, "OK 42")
        self.assertEqual(
            results[0].sent_message_id, 7,
        )

    def test_handler_exception_becomes_error_reply(self):
        def boom(args):
            raise RuntimeError("db down")
        bot = _fake_bot(commands=[_cmd("approve", "x")])
        d = OwnerDialogDispatcher(
            bot=bot, handlers={"approve": boom},
        )
        results = d.poll_and_dispatch()
        self.assertFalse(results[0].ok)
        self.assertIn("failed", results[0].reply)
        self.assertIn("db down", results[0].error)

    def test_reply_false_skips_send(self):
        bot = _fake_bot(commands=[_cmd("help")])
        d = OwnerDialogDispatcher(bot=bot)
        d.poll_and_dispatch(reply=False)
        bot.send_message.assert_not_called()

    def test_poll_exception_returns_empty(self):
        bot = _fake_bot()
        bot.poll_commands.side_effect = RuntimeError(
            "net down",
        )
        d = OwnerDialogDispatcher(bot=bot)
        self.assertEqual(d.poll_and_dispatch(), [])

    def test_send_failure_preserves_reply_marks_error(self):
        bot = _fake_bot(commands=[_cmd("help")])
        bot.send_message.side_effect = RuntimeError(
            "tg 429",
        )
        d = OwnerDialogDispatcher(bot=bot)
        results = d.poll_and_dispatch()
        self.assertTrue(results[0].reply)
        self.assertIn("tg 429", results[0].error)

    def test_history_bounded(self):
        bot = _fake_bot(commands=[_cmd("help")])
        d = OwnerDialogDispatcher(bot=bot)
        for _ in range(3):
            d.poll_and_dispatch()
        self.assertEqual(len(d.history()), 3)


class TestDefaultHandlers(unittest.TestCase):
    def test_factory_returns_expected_verbs(self):
        handlers = build_default_handlers()
        for verb in (
            "approve", "approve_all", "reject",
            "reject_all", "status", "limits",
            "pause", "resume", "digest",
        ):
            self.assertIn(verb, handlers)

    def test_approve_no_args_returns_usage(self):
        handlers = build_default_handlers()
        reply = handlers["approve"](())
        self.assertIn("Usage", reply)

    def test_reject_no_args_returns_usage(self):
        handlers = build_default_handlers()
        reply = handlers["reject"](())
        self.assertIn("Usage", reply)


class TestDict(unittest.TestCase):
    def test_result_as_dict(self):
        r = DispatchResult(
            update_id=1, verb="help", reply="x",
        )
        d = r.as_dict()
        self.assertEqual(d["verb"], "help")


if __name__ == "__main__":
    unittest.main()
