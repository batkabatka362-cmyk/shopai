"""Tests for pidfile + shopai autopilot-status CLI +
autopilot_status MCP tool."""
from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from core.system import pidfile as pf


class TestPidfileRoundTrip(unittest.TestCase):
    def test_write_then_read_alive(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            path = pf.write("daemon", base=base)
            self.assertTrue(path.exists())
            status = pf.read_status("daemon", base=base)
            self.assertTrue(status.running)
            self.assertEqual(status.pid, os.getpid())
            self.assertGreaterEqual(status.uptime_s, 0)

    def test_missing_file(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            status = pf.read_status("daemon", base=base)
            self.assertFalse(status.running)
            self.assertIn("not found", status.detail)

    def test_clear_removes_file(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            pf.write("daemon", base=base)
            self.assertTrue(
                pf.clear("daemon", base=base),
            )
            self.assertFalse(
                pf.read_status(
                    "daemon", base=base,
                ).running,
            )

    def test_corrupt_file(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            path = pf._path_for("daemon", base=base)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("not a pid\n")
            status = pf.read_status(
                "daemon", base=base,
            )
            self.assertFalse(status.running)
            self.assertIn("bad pid", status.detail)

    def test_dead_pid_stale_file(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            path = pf._path_for("daemon", base=base)
            path.parent.mkdir(parents=True, exist_ok=True)
            # Use a very high PID unlikely to be alive
            path.write_text("999999\n1000.0\n")
            status = pf.read_status(
                "daemon", base=base,
            )
            self.assertFalse(status.running)
            self.assertIn(
                "stale", status.detail,
            )

    def test_lifecycle_context_manager(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            with pf.lifecycle("daemon", base=base):
                self.assertTrue(
                    pf.read_status(
                        "daemon", base=base,
                    ).running,
                )
            # Cleared on exit
            self.assertFalse(
                pf.read_status(
                    "daemon", base=base,
                ).running,
            )

    def test_safe_name(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            path = pf.write(
                "dae/mon../../x", base=base,
            )
            # No path traversal
            self.assertTrue(
                str(path).startswith(str(base)),
            )


# ── CLI ──────────────────────────────────────────────────────


class TestCliAutopilotStatus(unittest.TestCase):
    def setUp(self):
        self._cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)

    def tearDown(self):
        os.chdir(self._cwd)
        self._tmp.cleanup()

    def test_json_not_running(self):
        import cli
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli._cmd_autopilot_status(
                log_path="data/autopilot_loop.log",
                as_json=True,
            )
        payload = json.loads(buf.getvalue())
        self.assertFalse(payload["daemon"]["running"])
        self.assertIsNone(payload["latest_cycle"])

    def test_table_running_false_has_start_hint(self):
        import cli
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli._cmd_autopilot_status(
                log_path="data/autopilot_loop.log",
                as_json=False,
            )
        out = buf.getvalue()
        self.assertIn("running: ✗", out)
        self.assertIn("run_daemon.py", out)

    def test_json_running_with_cycle(self):
        import cli
        # Pidfile with the current pid
        pf.write("daemon")
        # Sample log line
        log = Path("data/autopilot_loop.log")
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(
            json.dumps({
                "cycle": 7, "ts": 1_800_000_000,
                "mode": "dry_run",
                "launches": 2, "successful": 2,
                "duration_s": 1.5, "error": "",
            }) + "\n",
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli._cmd_autopilot_status(
                log_path=str(log), as_json=True,
            )
        payload = json.loads(buf.getvalue())
        self.assertTrue(payload["daemon"]["running"])
        self.assertEqual(
            payload["latest_cycle"]["cycle"], 7,
        )
        pf.clear("daemon")


# ── MCP ──────────────────────────────────────────────────────


class TestMcpAutopilotStatusTool(unittest.TestCase):
    def test_registered(self):
        from mcp_server.tools import build_default_registry
        reg = build_default_registry()
        names = {s.name for s in reg.list_tools()}
        self.assertIn("autopilot_status", names)

    def test_returns_structured_payload(self):
        from mcp_server.tools import (
            ToolCall, build_default_registry,
        )
        with tempfile.TemporaryDirectory() as td:
            old_cwd = os.getcwd()
            os.chdir(td)
            try:
                reg = build_default_registry()
                res = reg.call(ToolCall(
                    tool="autopilot_status",
                ))
                self.assertTrue(res.ok)
                self.assertIn("daemon", res.content)
                self.assertFalse(
                    res.content["daemon"]["running"],
                )
            finally:
                os.chdir(old_cwd)


if __name__ == "__main__":
    unittest.main()
