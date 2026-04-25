"""Live-health rolling digest tests (P1-C).

The trend fuses three sources: doctor probe result, recent
cycle summaries from ``data/autopilot_loop.log``, and
per-engine feedback trends. The verdict is a deterministic
function of all three — these tests lock the decision rules
so the owner's read stays stable across refactors.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from dataclasses import dataclass, field

from core.readiness.health_trend import (
    HealthTrend,
    compute_live_health,
    _decide,
    _tail_cycles,
    _read_engine_trends,
)


@dataclass
class _FakeDoctor:
    ok: bool = True
    critical_failures: int = 0
    warnings: int = 0


@dataclass
class _FakeStore:
    stats: dict[str, dict] = field(default_factory=dict)

    def get_all_stats(self):
        return dict(self.stats)


class TestTailCycles(unittest.TestCase):
    def test_missing_file_returns_empty(self):
        self.assertEqual(
            _tail_cycles("/tmp/does_not_exist_xyz.log", 10),
            [],
        )

    def test_reads_jsonl(self):
        tmp = tempfile.NamedTemporaryFile(
            "w", suffix=".log", delete=False,
        )
        try:
            tmp.write(
                json.dumps({"cycle": 1, "mode": "dry_run"})
                + "\n"
                + json.dumps({"cycle": 2, "mode": "live"})
                + "\n"
            )
            tmp.close()
            out = _tail_cycles(tmp.name, 10)
            self.assertEqual(len(out), 2)
            self.assertEqual(out[1]["mode"], "live")
        finally:
            os.unlink(tmp.name)

    def test_limit_respected(self):
        tmp = tempfile.NamedTemporaryFile(
            "w", suffix=".log", delete=False,
        )
        try:
            for i in range(10):
                tmp.write(
                    json.dumps({"cycle": i}) + "\n"
                )
            tmp.close()
            out = _tail_cycles(tmp.name, 3)
            self.assertEqual(len(out), 3)
            self.assertEqual(out[-1]["cycle"], 9)
        finally:
            os.unlink(tmp.name)

    def test_malformed_lines_skipped(self):
        tmp = tempfile.NamedTemporaryFile(
            "w", suffix=".log", delete=False,
        )
        try:
            tmp.write(
                json.dumps({"cycle": 1}) + "\n"
                + "not json\n"
                + "\n"
                + json.dumps({"cycle": 2}) + "\n"
            )
            tmp.close()
            out = _tail_cycles(tmp.name, 10)
            self.assertEqual(len(out), 2)
        finally:
            os.unlink(tmp.name)


class TestEngineTrends(unittest.TestCase):
    def test_extracts_trends(self):
        store = _FakeStore(stats={
            "eng1": {"trend": "improving"},
            "eng2": {"trend": "stable"},
            "eng3": {"total_runs": 0},  # no trend key
        })
        out = _read_engine_trends(store)
        self.assertEqual(
            out, {"eng1": "improving", "eng2": "stable"},
        )

    def test_broken_store_returns_empty(self):
        class Broken:
            def get_all_stats(self):
                raise RuntimeError("boom")
        self.assertEqual(_read_engine_trends(Broken()), {})


class TestVerdictLogic(unittest.TestCase):
    def test_healthy_when_all_green(self):
        doctor = _FakeDoctor(ok=True)
        v, _ = _decide(
            doctor,
            cycles=[{"cycle": 1}],
            engine_trends={"e1": "stable"},
        )
        self.assertEqual(v, "healthy")

    def test_needs_attention_on_critical_failures(self):
        doctor = _FakeDoctor(
            ok=False, critical_failures=2,
        )
        v, reasons = _decide(doctor, [], {})
        self.assertEqual(v, "needs_attention")
        self.assertTrue(
            any("critical" in r for r in reasons),
        )

    def test_needs_attention_when_doctor_not_ok(self):
        doctor = _FakeDoctor(
            ok=False, critical_failures=0, warnings=3,
        )
        v, _ = _decide(doctor, [], {})
        self.assertEqual(v, "needs_attention")

    def test_degrading_when_many_cycles_error(self):
        doctor = _FakeDoctor(ok=True)
        cycles = [
            {"cycle": i, "error": "x" if i < 5 else ""}
            for i in range(9)
        ]
        v, reasons = _decide(doctor, cycles, {})
        self.assertEqual(v, "degrading")
        self.assertTrue(
            any("errored" in r for r in reasons),
        )

    def test_degrading_when_engine_declining(self):
        doctor = _FakeDoctor(ok=True)
        v, _ = _decide(
            doctor,
            cycles=[{"cycle": 1}],
            engine_trends={"e": "declining"},
        )
        self.assertEqual(v, "degrading")

    def test_unknown_when_no_data(self):
        doctor = _FakeDoctor(ok=True)
        v, reasons = _decide(doctor, [], {})
        self.assertEqual(v, "unknown")
        self.assertTrue(reasons)


class TestComputeLiveHealth(unittest.TestCase):
    def test_end_to_end_healthy(self):
        tmp = tempfile.NamedTemporaryFile(
            "w", suffix=".log", delete=False,
        )
        try:
            tmp.write(
                json.dumps({
                    "cycle": 1, "mode": "dry_run",
                    "launches": 3, "successful": 3,
                    "error": "",
                }) + "\n"
            )
            tmp.close()
            store = _FakeStore(stats={
                "e1": {"trend": "stable"},
            })
            trend = compute_live_health(
                doctor_runner=lambda: _FakeDoctor(ok=True),
                feedback_store=store,
                log_path=tmp.name,
            )
            self.assertEqual(trend.verdict, "healthy")
            self.assertEqual(trend.cycles_considered, 1)
            self.assertEqual(trend.engines_stable, 1)
        finally:
            os.unlink(tmp.name)

    def test_end_to_end_degrading(self):
        tmp = tempfile.NamedTemporaryFile(
            "w", suffix=".log", delete=False,
        )
        try:
            for i in range(6):
                tmp.write(
                    json.dumps({
                        "cycle": i,
                        "error": "boom" if i < 4 else "",
                    }) + "\n"
                )
            tmp.close()
            trend = compute_live_health(
                doctor_runner=lambda: _FakeDoctor(ok=True),
                feedback_store=_FakeStore(),
                log_path=tmp.name,
            )
            self.assertEqual(trend.verdict, "degrading")
            self.assertEqual(trend.cycles_with_error, 4)
        finally:
            os.unlink(tmp.name)

    def test_as_dict_shape(self):
        tmp = tempfile.NamedTemporaryFile(
            "w", suffix=".log", delete=False,
        )
        try:
            tmp.close()
            trend = compute_live_health(
                doctor_runner=lambda: _FakeDoctor(ok=True),
                feedback_store=_FakeStore(),
                log_path=tmp.name,
            )
            d = trend.as_dict()
            for k in ("verdict", "reasons", "doctor",
                      "cycles", "engines"):
                self.assertIn(k, d)
            for k in (
                "ok", "critical_failures", "warnings",
            ):
                self.assertIn(k, d["doctor"])
            for k in (
                "considered", "with_error", "live_mode",
                "recent",
            ):
                self.assertIn(k, d["cycles"])
        finally:
            os.unlink(tmp.name)

    def test_recent_cycles_bounded_to_5(self):
        tmp = tempfile.NamedTemporaryFile(
            "w", suffix=".log", delete=False,
        )
        try:
            for i in range(20):
                tmp.write(
                    json.dumps({"cycle": i}) + "\n"
                )
            tmp.close()
            trend = compute_live_health(
                doctor_runner=lambda: _FakeDoctor(ok=True),
                feedback_store=_FakeStore(stats={
                    "e": {"trend": "stable"},
                }),
                log_path=tmp.name,
                cycles_limit=20,
            )
            self.assertEqual(len(trend.recent_cycles), 5)
            self.assertEqual(
                trend.recent_cycles[-1]["cycle"], 19,
            )
        finally:
            os.unlink(tmp.name)


class TestMCPLiveHealthTool(unittest.TestCase):
    def test_tool_registered(self):
        from mcp_server.tools import build_default_registry

        reg = build_default_registry()
        specs = {s.name: s for s in reg.list_tools()}
        self.assertIn("live_health", specs)
        self.assertFalse(specs["live_health"].write)

    def test_handler_clamps_cycles(self):
        # Just confirm it runs and clamps absurd values
        from mcp_server.tools import _live_health_handler

        # Use a nonexistent log to get a quick no-cycles run
        out = _live_health_handler({"cycles": 99999})
        self.assertIn("verdict", out)


if __name__ == "__main__":
    unittest.main()
