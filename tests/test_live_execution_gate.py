"""Centralised live-execution gate tests (quality audit follow-on).

Pre-audit: three call sites each copy-pasted the same
``os.getenv("SHOPAI_ENABLE_LIVE_EXECUTION", "") == "1"`` check
(publisher_bundle, campaign_activator, autopilot). A future
tweak in one would silently diverge from the others. This
test locks in the contract: all three paths now delegate to
``core.system.live_execution.is_live_execution_enabled()``.
"""
from __future__ import annotations

import os
import unittest

from core.system.live_execution import (
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


if __name__ == "__main__":
    unittest.main()
