"""Social scheduler wired into the daemon cycle."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ── Controller source-level wiring ──────────────────────────


class TestControllerWire:
    """Source-level checks — cheap, no cycle execution
    required. They protect against a future refactor that
    silently drops the wire."""

    def test_social_bootstrap_imported(self):
        import inspect
        from core.autonomous import controller as ctl
        src = inspect.getsource(ctl)
        assert (
            "from core.adapters.social.bootstrap import "
            "register_all as register_social"
        ) in src

    def test_social_phase_invokes_scheduler(self):
        import inspect
        from core.autonomous import controller as ctl
        src = inspect.getsource(ctl)
        # The phase exists and calls into our engine.
        assert "# Phase 5a1: SOCIAL SCHEDULER" in src
        assert "engines.social_scheduler" in src
        assert "process_due" in src

    def test_social_status_merged_into_adapter_status(self):
        import inspect
        from core.autonomous import controller as ctl
        src = inspect.getsource(ctl)
        # The status dict blends social_status in with the
        # other categories.
        assert "**social_status," in src


# ── Process_due is called with the cycle's router ───────────


class TestSchedulerInvocation:
    def test_process_due_receives_cycle_router(self):
        """Exercise the phase body in isolation. The phase
        pulls ``SocialScheduler.open()``, calls
        ``process_due(router=self._adapter_router)``, closes
        the scheduler, and stashes the summary."""
        from engines.social_scheduler import SocialScheduler

        fake_scheduler = MagicMock(spec=SocialScheduler)
        fake_scheduler.process_due.return_value = {
            "published": 3, "failed": 0, "skipped": 0,
            "processed": 3,
        }
        cycle_result: dict = {"phases": {}}
        fake_router = MagicMock()

        errors: dict = {}

        def _record(name, exc):
            errors[name] = str(exc)

        with patch.object(
            SocialScheduler, "open",
            return_value=fake_scheduler,
        ):
            try:
                sched = SocialScheduler.open()
                summary = sched.process_due(
                    router=fake_router, max_posts=20,
                )
                sched.close()
                cycle_result["phases"]["social_scheduler"] = (
                    summary
                )
            except Exception as exc:  # noqa: BLE001
                _record("social_scheduler", exc)

        fake_scheduler.process_due.assert_called_once()
        kwargs = fake_scheduler.process_due.call_args.kwargs
        assert kwargs["router"] is fake_router
        assert kwargs["max_posts"] == 20
        # Summary merged in.
        assert (
            cycle_result["phases"]["social_scheduler"][
                "published"
            ] == 3
        )
        assert errors == {}

    def test_exception_does_not_leak(self):
        """If the scheduler itself blows up, the cycle
        records the failure and keeps going — matches how
        every other phase in controller.py behaves."""
        from engines.social_scheduler import SocialScheduler

        fake_scheduler = MagicMock(spec=SocialScheduler)
        fake_scheduler.process_due.side_effect = RuntimeError(
            "boom",
        )
        errors: dict = {}

        def _record(name, exc):
            errors[name] = str(exc)

        with patch.object(
            SocialScheduler, "open",
            return_value=fake_scheduler,
        ):
            try:
                sched = SocialScheduler.open()
                sched.process_due(
                    router=None, max_posts=20,
                )
                sched.close()
            except Exception as exc:  # noqa: BLE001
                _record("social_scheduler", exc)

        assert "social_scheduler" in errors
        assert "boom" in errors["social_scheduler"]
