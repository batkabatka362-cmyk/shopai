"""Tests for shopai webhook CLI surface."""
from __future__ import annotations

import importlib.util
import json
from io import StringIO
from unittest.mock import patch

import pytest


def _load_cli():
    spec = importlib.util.spec_from_file_location("shopai_cli", "cli.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def cli():
    return _load_cli()


def _capture(fn, args):
    buf = StringIO()
    code = 0
    try:
        with patch("sys.stdout", buf):
            fn(args)
    except SystemExit as e:
        code = int(e.code) if e.code is not None else 0
    return buf.getvalue(), code


class _NS:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


class TestWebhookReceive:

    def test_missing_topic_errors(self, cli):
        args = _NS(topic=None, payload_json=None,
                   from_stdin=False, json=False)
        out, code = _capture(cli._cmd_webhook_receive, args)
        assert code == 1
        assert "missing --topic" in out

    def test_invalid_payload_json_errors(self, cli):
        args = _NS(topic="orders/create",
                   payload_json="{not_json",
                   from_stdin=False, json=False)
        out, code = _capture(cli._cmd_webhook_receive, args)
        assert code == 1
        assert "--payload-json invalid" in out

    def test_valid_event_ingested(self, cli):
        args = _NS(
            topic="orders/create",
            payload_json='{"id":"1","total_price":"50"}',
            from_stdin=False,
            json=False,
        )
        out, code = _capture(cli._cmd_webhook_receive, args)
        assert code == 0
        assert "ingested" in out.lower()

    def test_valid_event_json_output(self, cli):
        args = _NS(
            topic="orders/create",
            payload_json='{"id":"1"}',
            from_stdin=False,
            json=True,
        )
        out, _ = _capture(cli._cmd_webhook_receive, args)
        data = json.loads(out)
        assert "status" in data

    def test_stdin_envelope_parsed(self, cli):
        envelope = json.dumps({
            "topic": "orders/create",
            "payload": {"id": "1", "total_price": "10"},
        })
        args = _NS(
            topic=None, payload_json=None,
            from_stdin=True, json=True,
        )
        with patch("sys.stdin", StringIO(envelope)):
            out, code = _capture(cli._cmd_webhook_receive, args)
        assert code == 0
        data = json.loads(out)
        assert "status" in data

    def test_stdin_invalid_json_errors(self, cli):
        args = _NS(
            topic=None, payload_json=None,
            from_stdin=True, json=False,
        )
        with patch("sys.stdin", StringIO("{not_json")):
            out, code = _capture(cli._cmd_webhook_receive, args)
        assert code == 1
        assert "stdin parse failed" in out


class TestWebhookStats:

    def test_stats_renders(self, cli):
        args = _NS(json=False)
        out, code = _capture(cli._cmd_webhook_stats, args)
        assert code == 0
        assert "events_seen" in out

    def test_stats_json(self, cli):
        args = _NS(json=True)
        out, _ = _capture(cli._cmd_webhook_stats, args)
        data = json.loads(out)
        assert "events_seen" in data
