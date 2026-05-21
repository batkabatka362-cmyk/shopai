"""Tests for ``api.telegram_bot`` -- silent-failure fix.

Before: ``send()`` / ``_poll()`` / ``_handle()`` telemetry path
caught all exceptions and either returned False / passed
silently. An operator with messages-not-arriving / bot-not-
responding had no diagnostic signal.

After: each path logs the exception with context so the
warning surfaces in the standard logger output. The behavior
contract (return False / return / continue polling) is
preserved -- only the diagnostic side-channel is new.
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest


_BOT_LOGGER = "shopai.telegram.bot"


class _ListHandler(logging.Handler):
    """utils.logger.get_logger pins ``propagate=False`` on the
    shopai.* loggers so they don't double-log in production.
    That blocks caplog (which sits on the root). Attach a
    direct list handler instead so we can inspect what the
    target logger actually emitted."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def bot_log() -> _ListHandler:
    """List-handler attached to ``shopai.telegram.bot`` for the
    test, detached on teardown."""
    handler = _ListHandler()
    bot_logger = logging.getLogger(_BOT_LOGGER)
    original_level = bot_logger.level
    bot_logger.setLevel(logging.DEBUG)
    bot_logger.addHandler(handler)
    try:
        yield handler
    finally:
        bot_logger.removeHandler(handler)
        bot_logger.setLevel(original_level)


@pytest.fixture
def bot():
    from api.telegram_bot import TelegramBot
    # Use a non-empty token so the early-return guard doesn't
    # short-circuit the test.
    return TelegramBot(token="test-token")


def _messages(handler: _ListHandler) -> list[str]:
    return [r.getMessage() for r in handler.records]


class TestSendLogging:

    def test_send_failure_returns_false_and_logs(
        self, bot, bot_log,
    ):
        with patch(
            "api.telegram_bot.urllib.request.urlopen",
            side_effect=ConnectionError("network down"),
        ):
            result = bot.send(chat_id=123, text="hello")
        # Behavior contract preserved
        assert result is False
        # New: the failure is logged with context
        msgs = _messages(bot_log)
        assert any(
            "telegram send failed" in m
            and "chat=123" in m
            and "text_len=5" in m
            and "network down" in m
            for m in msgs
        )

    def test_send_success_does_not_log(self, bot, bot_log):
        fake_response = MagicMock()
        fake_response.__enter__ = lambda self: self
        fake_response.__exit__ = lambda self, *a: None
        with patch(
            "api.telegram_bot.urllib.request.urlopen",
            return_value=fake_response,
        ):
            result = bot.send(chat_id=123, text="hello")
        assert result is True
        # No warning logs on the happy path
        warnings = [
            r for r in bot_log.records
            if r.levelno >= logging.WARNING
        ]
        assert warnings == []

    def test_send_no_token_returns_false_without_log(
        self, bot_log,
    ):
        """No-token early-return shouldn't log -- it's a normal
        un-configured-bot state, not a runtime error."""
        from api.telegram_bot import TelegramBot
        bot = TelegramBot(token="")
        with patch.dict("os.environ", {}, clear=True):
            bot._token = ""
            result = bot.send(chat_id=123, text="hello")
        assert result is False
        assert bot_log.records == []


class TestPollLogging:

    def test_poll_iteration_failure_logs_and_continues(
        self, bot, bot_log,
    ):
        """A single failing poll iteration should:
        1. Log a warning with context (offset)
        2. NOT crash the polling thread
        3. Sleep and try again on the next iteration
        """
        call_count = {"n": 0}

        def fake_urlopen(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise ConnectionError("auth failed")
            # Stop the loop on the second iteration
            bot._running = False
            response = MagicMock()
            response.__enter__ = lambda self: self
            response.__exit__ = lambda self, *a: None
            response.read = lambda: b'{"result": []}'
            return response

        bot._running = True
        bot._offset = 42
        with patch(
            "api.telegram_bot.urllib.request.urlopen",
            side_effect=fake_urlopen,
        ), patch(
            "api.telegram_bot.time.sleep",
        ):
            bot._poll()

        msgs = _messages(bot_log)
        assert any(
            "telegram poll iteration failed" in m
            and "offset=42" in m
            and "auth failed" in m
            for m in msgs
        )


class TestHandleTelemetryLogging:

    def test_telemetry_failure_logs_debug(self, bot, bot_log):
        """When the data architecture import / call fails,
        log at debug (the bot's main work shouldn't be blocked
        by telemetry being down)."""
        update = {
            "message": {
                "text": "/status",
                "chat": {"id": 999},
            },
        }
        with patch(
            "api.telegram_bot.TelegramBot._cmd_status",
            return_value="status_ok",
        ), patch.object(
            bot, "send", return_value=True,
        ), patch.dict(
            "sys.modules",
            {"core.data.architecture": None},  # force ImportError
        ):
            bot._handle(update)

        debug_records = [
            r for r in bot_log.records
            if r.levelno == logging.DEBUG
        ]
        assert any(
            "telegram command telemetry failed" in r.getMessage()
            and "cmd=/status" in r.getMessage()
            for r in debug_records
        )


class TestCmdHandlerLogging:
    """The static ``_cmd_*`` handlers that returned "Unavailable"
    on failure now also log at debug. Same return contract."""

    def test_cmd_report_failure_logs_and_returns_unavailable(
        self, bot_log,
    ):
        from api.telegram_bot import TelegramBot
        with patch(
            "core.system.auto_scheduler.get_scheduler",
            side_effect=RuntimeError("scheduler down"),
        ):
            result = TelegramBot._cmd_report()
        assert result == "Unavailable"
        msgs = _messages(bot_log)
        assert any(
            "/report failed" in m and "scheduler down" in m
            for m in msgs
        )

    def test_cmd_memory_failure_logs(self, bot_log):
        from api.telegram_bot import TelegramBot
        with patch(
            "core.memory.intelligence.get_memory_intelligence",
            side_effect=RuntimeError("mi down"),
        ):
            result = TelegramBot._cmd_memory()
        assert result == "Unavailable"
        assert any(
            "/memory failed" in m for m in _messages(bot_log)
        )

    def test_cmd_alerts_failure_logs(self, bot_log):
        from api.telegram_bot import TelegramBot
        with patch(
            "core.system.alerts.get_alert_system",
            side_effect=RuntimeError("alerts down"),
        ):
            result = TelegramBot._cmd_alerts()
        assert result == "Unavailable"
        assert any(
            "/alerts failed" in m for m in _messages(bot_log)
        )
