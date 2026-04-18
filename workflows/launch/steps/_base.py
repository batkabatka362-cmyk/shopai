"""Step base class.

Every launch step inherits ``Step``. The pipeline runner handles
timing, error capture, retry policy, and outcome telemetry — a step
just implements ``execute(context)``.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any

from utils.logger import get_logger

from ..context import LaunchContext, StepResult


logger = get_logger("workflows.launch")


class StepFailure(RuntimeError):
    """Raised when a step cannot complete and the pipeline should stop.

    Use ``StepSkip`` instead when the failure is acceptable (e.g. an
    optional adapter is not configured)."""


class StepSkip(Exception):
    """Raised when a step should be marked skipped without breaking the
    pipeline (optional integration not configured)."""


class Step(ABC):
    """Base for all launch pipeline steps."""

    name: str = "step"
    optional: bool = False  # If True, step failures don't break the pipeline

    @abstractmethod
    def execute(self, context: LaunchContext) -> dict[str, Any]:
        """Run the step. Return a dict that will be stored on the
        relevant context attribute (the runner picks the right one
        from ``context_key``).

        Raise ``StepFailure`` for hard failures, ``StepSkip`` for
        soft skips (missing API key, optional integration disabled)."""

    def run(self, context: LaunchContext) -> StepResult:
        start = time.monotonic()
        try:
            output = self.execute(context)
            elapsed = time.monotonic() - start
            logger.info("Step %s OK in %.2fs", self.name, elapsed)
            return StepResult(
                name=self.name, status="ok",
                duration_s=elapsed, output=output or {},
            )
        except StepSkip as exc:
            elapsed = time.monotonic() - start
            logger.info("Step %s SKIPPED: %s", self.name, exc)
            return StepResult(
                name=self.name, status="skipped",
                duration_s=elapsed, error=str(exc),
            )
        except Exception as exc:  # noqa: BLE001
            elapsed = time.monotonic() - start
            logger.error(
                "Step %s FAILED in %.2fs: %s", self.name, elapsed, exc,
            )
            return StepResult(
                name=self.name, status="failed",
                duration_s=elapsed, error=f"{type(exc).__name__}: {exc}",
            )
