"""Autonomous Execution Engine — action dispatcher.

Validates action structure and classifies each action as ready
for the adapter layer. Does NOT execute anything itself — the
real execution lives in ``core/autonomous/agent_dispatcher.py``
(Shopify API, third-party apps, AI adapters).

**Cleanup note:** an earlier version of this module pretended to
dispatch actions by appending ``{"status": "dispatched", ...}``
entries and returning immediately. No handler was ever called,
but the shape of the result let downstream progress-tracking
engines count the fake dispatches as real successes. The
pretend-dispatch path is gone — non-dry-run actions are now
flagged ``"adapter_required"`` so callers know an adapter still
has to pick them up. Dry-run actions still mark themselves as
``"dry_run"`` and carry the validated metadata.
"""
from __future__ import annotations

import copy
from typing import Any


_SUPPORTED_TYPES = {"api_call", "db_query", "file_write", "notification", "webhook", "update", "create", "delete"}


def dispatch_actions(
    **kwargs: Any,
) -> dict[str, Any]:
    """Classify actions for downstream adapter dispatch.

    Args:
        **kwargs: Must include 'actions' list and 'execution_config' dict.

    Returns:
        Structured dict. Each entry in ``result.dispatched`` has
        one of:

        * ``status = "skipped"`` — unsupported ``action.type``
        * ``status = "dry_run"`` — dry-run mode; validated only
        * ``status = "adapter_required"`` — real execution needs
          the agent/adapter layer to pick it up (pre-cleanup this
          branch wrote a fake ``"dispatched"`` success instead)
    """
    try:
        actions = copy.deepcopy(kwargs.get("actions", []))
        config = kwargs.get("execution_config", {})
        dry_run = bool(config.get("dry_run", False))
        max_retries = int(config.get("max_retries", 3))

        dispatched: list[dict[str, Any]] = []

        for action in actions:
            action_type = str(action.get("type", ""))
            target = str(action.get("target", ""))
            params = action.get("params", {})

            if action_type not in _SUPPORTED_TYPES:
                dispatched.append({
                    "action": action,
                    "status": "skipped",
                    "result": None,
                    "error": f"Unsupported action type: {action_type}",
                })
                continue

            if dry_run:
                dispatched.append({
                    "action": action,
                    "status": "dry_run",
                    "result": {
                        "would_execute": True,
                        "type": action_type,
                        "target": target,
                        "params_count": len(params) if isinstance(params, dict) else 0,
                        "max_retries": max_retries,
                    },
                    "error": None,
                })
                continue

            # Not dry-run and action is supported: this module does
            # not execute anything real — hand the action to the
            # adapter layer via the envelope below. Pre-cleanup
            # this branch appended ``{"status": "dispatched"}``
            # with fabricated result data and let downstream
            # progress counters accept the fake success.
            dispatched.append({
                "action": action,
                "status": "adapter_required",
                "result": {
                    "type": action_type,
                    "target": target,
                    "params_count": len(params) if isinstance(params, dict) else 0,
                    "max_retries": max_retries,
                    "reason": (
                        "action_dispatcher does not execute; "
                        "route via core.autonomous.agent_dispatcher"
                    ),
                },
                "error": None,
            })

        return {
            "status": "success",
            "result": {
                "dispatched": dispatched,
                "total": len(dispatched),
                "dry_run": dry_run,
            },
        }
    except Exception as exc:
        return {"status": "error", "error": f"Action dispatch failed: {exc}"}
