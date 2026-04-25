"""Centralised live-execution gate tests (quality audit follow-on).

Pre-audit: three call sites each copy-pasted the same
``os.getenv("SHOPAI_ENABLE_LIVE_EXECUTION", "") == "1"`` check
(publisher_bundle, campaign_activator, autopilot). A future
tweak in one would silently diverge from the others. This
test locks in the contract: all three paths now delegate to
``core.system.live_execution.is_live_execution_enabled()``.

Also covers the ``check_gate_drift`` invariant — when the
owner / system flips the env flag mid-launch, the drift is
logged (never silently overrides the caller's intent).
"""
from __future__ import annotations

import logging
import os
import unittest

from core.system.live_execution import (
    check_gate_drift,
    is_live_execution_enabled,
)


class _EnvSandbox:
    KEY = "SHOPAI_ENABLE_LIVE_EXECUTION"

    def __enter__(self):
        self._orig = os.environ.get(self.KEY)
        os.environ.pop(self.KEY, None)
        return self

    def __exit__(self, *a):
        if self._orig is None:
            os.environ.pop(self.KEY, None)
        else:
            os.environ[self.KEY] = self._orig


class TestGate(unittest.TestCase):
    def test_default_off(self):
        with _EnvSandbox():
            self.assertFalse(is_live_execution_enabled())

    def test_one_enables(self):
        with _EnvSandbox():
            os.environ["SHOPAI_ENABLE_LIVE_EXECUTION"] = "1"
            self.assertTrue(is_live_execution_enabled())

    def test_other_values_disabled(self):
        with _EnvSandbox():
            for val in ("0", "true", "yes", ""):
                os.environ[
                    "SHOPAI_ENABLE_LIVE_EXECUTION"
                ] = val
                self.assertFalse(
                    is_live_execution_enabled(),
                    f"{val!r} must NOT enable live",
                )


class TestCallerConsistency(unittest.TestCase):
    """Every write-path wrapper delegates to the canonical
    function — no shadow implementations."""

    def test_publisher_bundle_uses_canonical(self):
        with _EnvSandbox():
            from execution.launch.publisher_bundle import (
                _enable_live_execution as _pub,
            )
            self.assertFalse(_pub())
            os.environ["SHOPAI_ENABLE_LIVE_EXECUTION"] = "1"
            self.assertTrue(_pub())

    def test_campaign_activator_uses_canonical(self):
        with _EnvSandbox():
            from execution.launch.campaign_activator import (
                _enable_live_execution as _act,
            )
            self.assertFalse(_act())
            os.environ["SHOPAI_ENABLE_LIVE_EXECUTION"] = "1"
            self.assertTrue(_act())

    def test_autopilot_uses_canonical(self):
        with _EnvSandbox():
            from execution.launch.autopilot import (
                _live_enabled,
            )
            self.assertFalse(_live_enabled())
            os.environ["SHOPAI_ENABLE_LIVE_EXECUTION"] = "1"
            self.assertTrue(_live_enabled())

    def test_all_three_agree(self):
        """If the canonical gate flips, all three wrappers
        flip with it — no drift possible."""
        with _EnvSandbox():
            from execution.launch.publisher_bundle import (
                _enable_live_execution as _pub,
            )
            from execution.launch.campaign_activator import (
                _enable_live_execution as _act,
            )
            from execution.launch.autopilot import (
                _live_enabled,
            )
            # All off
            self.assertEqual(
                (_pub(), _act(), _live_enabled()),
                (False, False, False),
            )
            # All on
            os.environ["SHOPAI_ENABLE_LIVE_EXECUTION"] = "1"
            self.assertEqual(
                (_pub(), _act(), _live_enabled()),
                (True, True, True),
            )


class TestGateDrift(unittest.TestCase):
    """``check_gate_drift`` is a defensive invariant at the
    money-commit point in publisher + activator. It must log
    (not raise) when env flips mid-launch, and must not
    second-guess the caller's computed ``dry_run``."""

    def _attach_capture(self):
        records: list[logging.LogRecord] = []
        dlog = logging.getLogger(
            "shopai.core.system.live_execution",
        )

        class _H(logging.Handler):
            def emit(self, r):
                records.append(r)

        h = _H(level=logging.WARNING)
        dlog.addHandler(h)
        return dlog, h, records

    def test_no_drift_silent(self):
        with _EnvSandbox():
            # request.live=True, env on → live, no drift vs
            # initial dry_run=False
            os.environ["SHOPAI_ENABLE_LIVE_EXECUTION"] = "1"
            dlog, h, records = self._attach_capture()
            try:
                drifted = check_gate_drift(
                    initial_dry_run=False,
                    request_live=True,
                    step="t",
                )
            finally:
                dlog.removeHandler(h)
            self.assertFalse(drifted)
            self.assertEqual(records, [])

    def test_env_flip_to_off_detected(self):
        with _EnvSandbox():
            # Start live → entry computed dry_run=False.
            # Env flips to off before commit.
            os.environ.pop("SHOPAI_ENABLE_LIVE_EXECUTION", None)
            dlog, h, records = self._attach_capture()
            try:
                drifted = check_gate_drift(
                    initial_dry_run=False,
                    request_live=True,
                    step="activate_campaign",
                )
            finally:
                dlog.removeHandler(h)
            self.assertTrue(drifted)
            self.assertTrue(records)
            self.assertIn(
                "activate_campaign",
                records[0].getMessage(),
            )

    def test_env_flip_to_on_detected(self):
        with _EnvSandbox():
            # Entry: env off → dry_run=True. Before commit env
            # flips on. Pipeline must stay dry_run and log.
            os.environ["SHOPAI_ENABLE_LIVE_EXECUTION"] = "1"
            dlog, h, records = self._attach_capture()
            try:
                drifted = check_gate_drift(
                    initial_dry_run=True,
                    request_live=True,
                    step="launch_campaign",
                )
            finally:
                dlog.removeHandler(h)
            self.assertTrue(drifted)
            self.assertTrue(records)

    def test_request_not_live_never_drifts(self):
        with _EnvSandbox():
            # request.live=False means dry_run=True always.
            # Env flip cannot produce drift.
            for val in ("", "0", "1"):
                if val:
                    os.environ[
                        "SHOPAI_ENABLE_LIVE_EXECUTION"
                    ] = val
                else:
                    os.environ.pop(
                        "SHOPAI_ENABLE_LIVE_EXECUTION", None,
                    )
                self.assertFalse(check_gate_drift(
                    initial_dry_run=True,
                    request_live=False,
                    step="t",
                ))


if __name__ == "__main__":
    unittest.main()
