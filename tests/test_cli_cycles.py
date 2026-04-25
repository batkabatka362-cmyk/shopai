"""Tests for ``shopai cycles`` CLI + matching MCP
``recent_cycles`` tool."""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import cli as cli_mod
from mcp_server.tools import (
    ToolCall,
    build_default_registry,
)


def _write_log(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def _sample_rows(n: int) -> list[dict]:
    return [
        {
            "cycle": i + 1,
            "ts": 1_800_000_000 + i * 60,
            "mode": "dry_run" if i % 2 else "live",
            "launches": 2,
            "successful": 2 - (1 if i == 3 else 0),
            "distilled": 0,
            "accepted": 0,
            "duration_s": 0.5 + i * 0.1,
            "error": "timeout" if i == 3 else "",
        }
        for i in range(n)
    ]


class TestCyclesMissingLog(unittest.TestCase):
    def test_table_hint_when_log_missing(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli_mod._cmd_cycles(
                log_path="/tmp/does_not_exist_xxx.log",
                limit=10,
                as_json=False,
            )
        out = buf.getvalue()
        self.assertIn("No autopilot log", out)
        self.assertIn("daemon", out)

    def test_json_empty_when_log_missing(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli_mod._cmd_cycles(
                log_path="/tmp/does_not_exist_xxx.log",
                limit=10,
                as_json=True,
            )
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["cycles"], [])
        self.assertIn("note", payload)


class TestCyclesReading(unittest.TestCase):
    def test_table_shows_rows(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "log.jsonl"
            _write_log(path, _sample_rows(3))
            buf = io.StringIO()
            with redirect_stdout(buf):
                cli_mod._cmd_cycles(
                    log_path=str(path),
                    limit=10,
                    as_json=False,
                )
            out = buf.getvalue()
            self.assertIn("Autopilot cycles", out)
            self.assertIn("launches=", out)
            self.assertIn("successful=", out)

    def test_json_returns_structured_payload(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "log.jsonl"
            _write_log(path, _sample_rows(5))
            buf = io.StringIO()
            with redirect_stdout(buf):
                cli_mod._cmd_cycles(
                    log_path=str(path),
                    limit=10,
                    as_json=True,
                )
            payload = json.loads(buf.getvalue())
            self.assertEqual(payload["total"], 5)
            self.assertEqual(payload["returned"], 5)
            self.assertEqual(len(payload["cycles"]), 5)

    def test_limit_tail(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "log.jsonl"
            _write_log(path, _sample_rows(10))
            buf = io.StringIO()
            with redirect_stdout(buf):
                cli_mod._cmd_cycles(
                    log_path=str(path),
                    limit=3,
                    as_json=True,
                )
            payload = json.loads(buf.getvalue())
            self.assertEqual(payload["total"], 10)
            self.assertEqual(payload["returned"], 3)
            # Tail — cycles 8, 9, 10
            self.assertEqual(
                [c["cycle"] for c in payload["cycles"]],
                [8, 9, 10],
            )

    def test_malformed_lines_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "log.jsonl"
            with path.open("w") as fh:
                fh.write(json.dumps(_sample_rows(1)[0]) + "\n")
                fh.write("not json\n")
                fh.write(json.dumps(_sample_rows(1)[0]) + "\n")
            buf = io.StringIO()
            with redirect_stdout(buf):
                cli_mod._cmd_cycles(
                    log_path=str(path),
                    limit=10,
                    as_json=True,
                )
            payload = json.loads(buf.getvalue())
            self.assertEqual(payload["total"], 2)

    def test_empty_log_shows_hint(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "log.jsonl"
            path.write_text("")
            buf = io.StringIO()
            with redirect_stdout(buf):
                cli_mod._cmd_cycles(
                    log_path=str(path),
                    limit=10,
                    as_json=False,
                )
            self.assertIn("empty", buf.getvalue())


class TestMcpRecentCyclesTool(unittest.TestCase):
    def test_registered(self):
        reg = build_default_registry()
        names = {s.name for s in reg.list_tools()}
        self.assertIn("recent_cycles", names)

    def test_returns_cycles(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "log.jsonl"
            _write_log(path, _sample_rows(3))
            reg = build_default_registry()
            res = reg.call(ToolCall(
                tool="recent_cycles",
                arguments={
                    "log_path": str(path),
                    "limit": 2,
                },
            ))
        self.assertTrue(res.ok)
        self.assertEqual(res.content["total"], 3)
        self.assertEqual(res.content["returned"], 2)
        self.assertEqual(
            [c["cycle"] for c in res.content["cycles"]],
            [2, 3],
        )

    def test_missing_log_returns_empty(self):
        reg = build_default_registry()
        res = reg.call(ToolCall(
            tool="recent_cycles",
            arguments={
                "log_path": "/tmp/missing_xyz.log",
            },
        ))
        self.assertTrue(res.ok)
        self.assertEqual(res.content["cycles"], [])
        self.assertIn("note", res.content)

    def test_limit_clamped(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "log.jsonl"
            _write_log(path, _sample_rows(5))
            reg = build_default_registry()
            res = reg.call(ToolCall(
                tool="recent_cycles",
                arguments={
                    "log_path": str(path),
                    "limit": 10_000,
                },
            ))
        self.assertTrue(res.ok)
        # 10_000 clamped to 1000, so we got all 5
        self.assertEqual(res.content["returned"], 5)


if __name__ == "__main__":
    unittest.main()
