"""Tests for cycle-error digest — module + CLI + MCP."""
from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

from agents.owner_dialog.cycle_error_digest import (
    ErrorDigestResult,
    send_error_digest,
)


def _write_log(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def _cycle(
    cycle: int, ts: float, error: str = "",
) -> dict:
    return {
        "cycle": cycle, "ts": ts,
        "mode": "dry_run",
        "launches": 1, "successful": 1 if not error else 0,
        "duration_s": 0.5, "error": error,
    }


# ── Module ──────────────────────────────────────────────────


class TestDigestComposition(unittest.TestCase):
    def test_no_errors_returns_all_clear(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "log.jsonl"
            _write_log(path, [
                _cycle(1, 1_800_000_000),
                _cycle(2, 1_800_000_060),
            ])
            result = send_error_digest(
                log_path=str(path),
                hours=24.0,
                dry_run=True,
                now_fn=lambda: 1_800_000_120,
            )
        self.assertFalse(result.sent)
        self.assertTrue(result.dry_run)
        self.assertEqual(result.cycles_scanned, 2)
        self.assertEqual(result.errors_found, 0)
        self.assertIn("no errors", result.text)

    def test_errors_listed_in_digest(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "log.jsonl"
            _write_log(path, [
                _cycle(1, 1_800_000_000),
                _cycle(
                    2, 1_800_000_060,
                    error="ShopifyConnectionError",
                ),
                _cycle(3, 1_800_000_120),
                _cycle(
                    4, 1_800_000_180,
                    error="Meta API 502",
                ),
            ])
            result = send_error_digest(
                log_path=str(path),
                hours=24.0,
                dry_run=True,
                now_fn=lambda: 1_800_000_240,
            )
        self.assertEqual(result.errors_found, 2)
        self.assertIn("2 errors", result.text)
        self.assertIn(
            "ShopifyConnectionError", result.text,
        )
        self.assertIn("Meta API 502", result.text)

    def test_window_filter(self):
        """Cycles outside the window are excluded."""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "log.jsonl"
            # Error cycle 48h ago, error cycle 1h ago
            _write_log(path, [
                _cycle(
                    1, 1_800_000_000 - 48 * 3600,
                    error="Ancient crash",
                ),
                _cycle(
                    2, 1_800_000_000 - 3600,
                    error="Recent crash",
                ),
            ])
            result = send_error_digest(
                log_path=str(path),
                hours=24.0,
                dry_run=True,
                now_fn=lambda: 1_800_000_000,
            )
        self.assertEqual(result.errors_found, 1)
        self.assertNotIn("Ancient", result.text)
        self.assertIn("Recent", result.text)

    def test_missing_log_yields_zero_errors(self):
        result = send_error_digest(
            log_path="/tmp/does_not_exist_xyz.log",
            hours=24.0,
            dry_run=True,
            now_fn=lambda: 1_800_000_000,
        )
        self.assertEqual(result.cycles_scanned, 0)
        self.assertEqual(result.errors_found, 0)


class TestSendPath(unittest.TestCase):
    def test_adapter_unavailable_surfaces_reason(self):
        fake_adapter = MagicMock()
        fake_adapter.is_available.return_value = False
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "log.jsonl"
            _write_log(path, [
                _cycle(
                    1, 1_800_000_000,
                    error="boom",
                ),
            ])
            result = send_error_digest(
                log_path=str(path),
                hours=24.0,
                dry_run=False,
                adapter=fake_adapter,
                now_fn=lambda: 1_800_000_060,
            )
        self.assertFalse(result.sent)
        self.assertIn(
            "telegram not configured",
            result.reason,
        )

    def test_send_returns_none_surfaces_reason(self):
        fake_adapter = MagicMock()
        fake_adapter.is_available.return_value = True
        fake_adapter.send_message.return_value = None
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "log.jsonl"
            _write_log(path, [
                _cycle(
                    1, 1_800_000_000, error="boom",
                ),
            ])
            result = send_error_digest(
                log_path=str(path),
                adapter=fake_adapter,
                now_fn=lambda: 1_800_000_060,
            )
        self.assertFalse(result.sent)
        self.assertIn("None", result.reason)

    def test_successful_send(self):
        fake_adapter = MagicMock()
        fake_adapter.is_available.return_value = True
        fake_adapter.send_message.return_value = 999
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "log.jsonl"
            _write_log(path, [
                _cycle(1, 1_800_000_000, error="x"),
            ])
            result = send_error_digest(
                log_path=str(path),
                adapter=fake_adapter,
                chat_id="12345",
                now_fn=lambda: 1_800_000_060,
            )
        self.assertTrue(result.sent)
        self.assertEqual(result.message_id, 999)
        fake_adapter.send_message.assert_called_once()
        kwargs = fake_adapter.send_message.call_args.kwargs
        self.assertEqual(kwargs["chat_id"], "12345")

    def test_send_raise_surfaces_reason(self):
        fake_adapter = MagicMock()
        fake_adapter.is_available.return_value = True
        fake_adapter.send_message.side_effect = (
            RuntimeError("network")
        )
        result = send_error_digest(
            log_path="/tmp/none.log",
            adapter=fake_adapter,
            now_fn=lambda: 1_800_000_060,
        )
        self.assertFalse(result.sent)
        self.assertIn("send raised", result.reason)


# ── CLI ──────────────────────────────────────────────────────


class TestCli(unittest.TestCase):
    def test_dry_run_prints_preview(self):
        import cli
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "log.jsonl"
            _write_log(path, [
                _cycle(1, 1_800_000_000, error="x"),
            ])
            # freeze time via monkeypatch on send_error_digest
            buf = io.StringIO()
            orig = cli._cmd_notify_errors
            with redirect_stdout(buf):
                cli._cmd_notify_errors(
                    hours=24.0,
                    log_path=str(path),
                    dry_run=True,
                    chat_id=None,
                    as_json=False,
                )
            out = buf.getvalue()
            self.assertIn("dry run", out.lower())
            self.assertIn("autopilot", out.lower())

    def test_json_output(self):
        import cli
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "log.jsonl"
            _write_log(path, [_cycle(1, 1_800_000_000)])
            buf = io.StringIO()
            with redirect_stdout(buf):
                cli._cmd_notify_errors(
                    hours=24.0,
                    log_path=str(path),
                    dry_run=True,
                    chat_id=None,
                    as_json=True,
                )
            payload = json.loads(buf.getvalue())
            self.assertEqual(
                payload["cycles_scanned"], 1,
            )
            self.assertEqual(payload["errors_found"], 0)


# ── MCP ──────────────────────────────────────────────────────


class TestMcpTool(unittest.TestCase):
    def test_registered(self):
        from mcp_server.tools import build_default_registry
        reg = build_default_registry()
        names = {s.name for s in reg.list_tools()}
        self.assertIn("notify_errors", names)

    def test_dry_run_returns_structured_result(self):
        from mcp_server.tools import (
            ToolCall, build_default_registry,
        )
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "log.jsonl"
            _write_log(path, [
                _cycle(1, 1_800_000_000, error="x"),
            ])
            reg = build_default_registry()
            res = reg.call(ToolCall(
                tool="notify_errors",
                arguments={
                    "log_path": str(path),
                    "hours": 9999.0,
                    "dry_run": True,
                },
            ))
        self.assertTrue(res.ok)
        self.assertTrue(res.content["dry_run"])
        self.assertEqual(
            res.content["errors_found"], 1,
        )
        self.assertIn("text", res.content)


if __name__ == "__main__":
    unittest.main()
