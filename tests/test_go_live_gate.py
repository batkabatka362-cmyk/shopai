"""Go-live readiness gate tests.

`shopai ready-for-live` is the single pre-T1 verb. Locks
the verdict logic so a fresh install prints the right list
of fixes and a prepared install prints READY.
"""
from __future__ import annotations

import unittest
from dataclasses import dataclass, field
from unittest.mock import patch

from core.readiness.go_live_gate import (
    CheckResult,
    GoLiveReport,
    run_go_live_gate,
    _check_env,
    _check_doctor,
    _check_learning_loop,
    _check_live_health,
    _check_live_gate_off,
)


@dataclass
class _FakeDoctor:
    ok: bool = True
    critical_failures: int = 0
    warnings: int = 0


@dataclass
class _FakeHealth:
    verdict: str = "healthy"


class TestEnvCheck(unittest.TestCase):
    def test_missing_url(self):
        with patch.dict(
            "os.environ",
            {
                "SHOPAI_SHOPIFY_URL": "",
                "SHOPAI_SHOPIFY_KEY": "shpat_x",
            },
            clear=False,
        ):
            r = _check_env()
        self.assertFalse(r.ok)
        self.assertIn("SHOPAI_SHOPIFY_URL", r.reason)

    def test_missing_key_and_secret(self):
        with patch.dict(
            "os.environ",
            {
                "SHOPAI_SHOPIFY_URL": "x.myshopify.com",
                "SHOPAI_SHOPIFY_KEY": "",
                "SHOPAI_SHOPIFY_CLIENT_SECRET": "",
            },
            clear=False,
        ):
            r = _check_env()
        self.assertFalse(r.ok)

    def test_both_present(self):
        with patch.dict(
            "os.environ",
            {
                "SHOPAI_SHOPIFY_URL": "x.myshopify.com",
                "SHOPAI_SHOPIFY_KEY": "shpat_x",
            },
            clear=False,
        ):
            r = _check_env()
        self.assertTrue(r.ok)

    def test_oauth_secret_sufficient(self):
        with patch.dict(
            "os.environ",
            {
                "SHOPAI_SHOPIFY_URL": "x.myshopify.com",
                "SHOPAI_SHOPIFY_KEY": "",
                "SHOPAI_SHOPIFY_CLIENT_SECRET": "secret_x",
            },
            clear=False,
        ):
            r = _check_env()
        self.assertTrue(r.ok)


class TestDoctorCheck(unittest.TestCase):
    def test_critical_failures_block(self):
        r = _check_doctor(
            doctor_runner=lambda: _FakeDoctor(
                ok=False, critical_failures=2,
            ),
        )
        self.assertFalse(r.ok)
        self.assertIn("critical", r.reason)

    def test_no_failures_passes(self):
        r = _check_doctor(
            doctor_runner=lambda: _FakeDoctor(ok=True),
        )
        self.assertTrue(r.ok)

    def test_doctor_raises_blocks(self):
        def raiser():
            raise RuntimeError("boom")

        r = _check_doctor(doctor_runner=raiser)
        self.assertFalse(r.ok)
        self.assertIn("boom", r.reason)


class TestLearningLoopCheck(unittest.TestCase):
    def test_happy_path(self):
        """Running replay produces feedback entries — the
        wire from last session should hold."""
        from core.learning.feedback_store import (
            reset_feedback_store_for_tests,
        )
        import tempfile

        d = tempfile.mkdtemp(prefix="gate_ll_")
        reset_feedback_store_for_tests(store_dir=d)
        try:
            r = _check_learning_loop()
            self.assertTrue(
                r.ok,
                msg=f"reason={r.reason}",
            )
            self.assertIn("feedback entries", r.reason)
        finally:
            reset_feedback_store_for_tests()


class TestLiveHealthCheck(unittest.TestCase):
    def test_healthy_passes(self):
        r = _check_live_health(
            live_health_runner=lambda: _FakeHealth(
                verdict="healthy",
            ),
        )
        self.assertTrue(r.ok)

    def test_unknown_passes_for_fresh_setup(self):
        """A fresh install has no cycles yet — unknown is
        expected and must not block."""
        r = _check_live_health(
            live_health_runner=lambda: _FakeHealth(
                verdict="unknown",
            ),
        )
        self.assertTrue(r.ok)

    def test_degrading_blocks(self):
        r = _check_live_health(
            live_health_runner=lambda: _FakeHealth(
                verdict="degrading",
            ),
        )
        self.assertFalse(r.ok)

    def test_needs_attention_blocks(self):
        r = _check_live_health(
            live_health_runner=lambda: _FakeHealth(
                verdict="needs_attention",
            ),
        )
        self.assertFalse(r.ok)


class TestLiveGateOffCheck(unittest.TestCase):
    def test_gate_off_ok(self):
        with patch.dict(
            "os.environ",
            {"SHOPAI_ENABLE_LIVE_EXECUTION": ""},
            clear=False,
        ):
            r = _check_live_gate_off()
        self.assertTrue(r.ok)
        self.assertIn("disabled", r.reason)

    def test_gate_on_warns_but_passes(self):
        """If the owner already flipped live on, the gate
        doesn't re-block — they know what they're doing."""
        with patch.dict(
            "os.environ",
            {"SHOPAI_ENABLE_LIVE_EXECUTION": "1"},
            clear=False,
        ):
            r = _check_live_gate_off()
        self.assertTrue(r.ok)
        self.assertIn("already", r.reason)


class TestEndToEnd(unittest.TestCase):
    def test_blocked_prints_fix_list(self):
        with patch.dict(
            "os.environ",
            {
                "SHOPAI_SHOPIFY_URL": "",
                "SHOPAI_SHOPIFY_KEY": "",
                "SHOPAI_SHOPIFY_CLIENT_SECRET": "",
            },
            clear=False,
        ):
            report = run_go_live_gate(
                doctor_runner=lambda: _FakeDoctor(ok=True),
                live_health_runner=lambda: _FakeHealth(
                    verdict="healthy",
                ),
                skip_learning_loop=True,
            )
        self.assertEqual(report.verdict, "BLOCKED")
        blocking = report.blocking()
        self.assertTrue(blocking)
        # env must be in the blocking list
        names = {c.name for c in blocking}
        self.assertIn("env", names)

    def test_ready_when_everything_green(self):
        with patch.dict(
            "os.environ",
            {
                "SHOPAI_SHOPIFY_URL": "x.myshopify.com",
                "SHOPAI_SHOPIFY_KEY": "shpat_x",
                "SHOPAI_ENABLE_LIVE_EXECUTION": "",
            },
            clear=False,
        ):
            report = run_go_live_gate(
                doctor_runner=lambda: _FakeDoctor(ok=True),
                live_health_runner=lambda: _FakeHealth(
                    verdict="healthy",
                ),
                skip_learning_loop=True,
            )
        self.assertEqual(report.verdict, "READY")
        self.assertEqual(report.blocking(), [])

    def test_as_dict_shape(self):
        report = run_go_live_gate(
            doctor_runner=lambda: _FakeDoctor(ok=True),
            live_health_runner=lambda: _FakeHealth(
                verdict="healthy",
            ),
            skip_learning_loop=True,
        )
        d = report.as_dict()
        self.assertIn("verdict", d)
        self.assertIn("checks", d)
        self.assertIn("blocking", d)


class TestMCPReadyForLive(unittest.TestCase):
    def test_tool_registered(self):
        from mcp_server.tools import build_default_registry

        reg = build_default_registry()
        specs = {s.name: s for s in reg.list_tools()}
        self.assertIn("ready_for_live", specs)
        self.assertFalse(specs["ready_for_live"].write)

    def test_handler_skip_learning_loop(self):
        from mcp_server.tools import (
            _ready_for_live_handler,
        )
        out = _ready_for_live_handler({
            "skip_learning_loop": True,
        })
        self.assertIn("verdict", out)
        self.assertIn("checks", out)


if __name__ == "__main__":
    unittest.main()
