"""Adapter post-cycle hooks — stub.

``AutonomousController.run_once`` invokes ``run_post_cycle_hooks``
once the main decision cycle finishes so adapters can post
summaries to external systems (Obsidian, webhooks, etc.) without
blocking the brain. No hooks are wired in this build — the
function returns ``{"enabled": False}`` so the controller records
the phase as no-op and keeps running.
"""
from __future__ import annotations

from typing import Any


def run_post_cycle_hooks(
    router: Any,
    cycle_result: dict[str, Any],
    data: dict[str, Any],
    phase_errors: dict[str, Any],
) -> dict[str, Any]:
    return {"enabled": False}
