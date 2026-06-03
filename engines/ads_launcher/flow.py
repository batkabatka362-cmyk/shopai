"""Ads Launcher Engine — Pattern Q envelope wrapper.

Wraps the launch / status / connect helpers into a single engine
that returns the canonical {status, data, meta, error} shape.

The CLI consumes either this engine OR the helpers directly. The
engine path is here for substrate-uniformity (Pattern Q runtime
audit, AGI loop consumption, autonomy domain potential).
"""
from __future__ import annotations

import copy
import logging
import time
from dataclasses import asdict
from typing import Any

from .launcher import launch_first_campaign
from .status import get_all_status, get_platform_status

logger = logging.getLogger(__name__)


class AdsLauncherEngine:
    """Operator-facing wrapper around the ads adapters."""

    ENGINE_NAME = "ads_launcher"

    def run(
        self, input_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        start = time.monotonic()
        payload = self._safe_copy(input_payload)
        if payload is None:
            return self._fail("Input copy failed", 0.0)
        if not isinstance(payload, dict):
            return self._fail("Input must be a dict", 0.0)
        if payload.get("status") == "fail":
            return self._fail(
                payload.get("error", "Upstream failure"), 0.0,
            )

        data = payload.get("data") or {}
        if not isinstance(data, dict):
            data = {}

        # Default action is 'status' — read-only diagnostic
        # that always works and never writes.
        action = (data.get("action") or "status").lower()

        if action == "status":
            return self._success(
                {
                    "action": "status",
                    "platforms": {
                        p: asdict(s) for p, s in
                        get_all_status().items()
                    },
                    "next_action": _status_next_action(),
                },
                start,
            )

        if action == "launch":
            platform = (data.get("platform") or "meta").lower()
            # Refuse to launch if the platform isn't ready.
            ps = get_platform_status(platform)
            if not ps.ready:
                return self._success(
                    {
                        "action": "launch",
                        "platform": platform,
                        "launched": False,
                        "blocked_reason": ps.detail,
                        "missing_env_vars": ps.env_vars_needed,
                        "next_action": (
                            f"Connect first: shopai ads "
                            f"connect {platform} --token ... "
                            "--account-id ..."
                        ),
                    },
                    start,
                )

            res = launch_first_campaign(
                platform=platform,
                daily_budget_usd=float(
                    data.get("daily_budget_usd", 10.0),
                ),
                name=data.get("name"),
                niche=data.get("niche"),
                objective=data.get("objective"),
            )
            return self._success(
                {
                    "action": "launch",
                    "platform": platform,
                    "launched": res.success,
                    "campaign_id": res.campaign_id,
                    "campaign_name": res.campaign_name,
                    "daily_budget_usd": res.daily_budget_usd,
                    "status": res.status,
                    "next_url": res.next_url,
                    "error": res.error or None,
                    "next_action": (
                        (
                            f"Open in Manager: {res.next_url} "
                            "(add ad sets + creative + "
                            "activate)"
                        ) if res.success else (
                            f"Launch failed: {res.error}"
                        )
                    ),
                },
                start,
            )

        return self._fail(
            f"unsupported action '{action}'. Use status / launch.",
            time.monotonic() - start,
        )

    # ── Internal ──────────────────────────────────────────

    @staticmethod
    def _safe_copy(payload: Any) -> Any:
        if payload is None:
            return {}
        try:
            return copy.deepcopy(payload)
        except Exception as exc:  # noqa: BLE001
            logger.debug("input copy raised: %s", exc)
            return None

    def _success(
        self, data: dict[str, Any], start: float,
    ) -> dict[str, Any]:
        return {
            "status": "success",
            "data": data,
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(),
                ),
                "elapsed_seconds": round(
                    time.monotonic() - start, 3,
                ),
            },
            "error": None,
        }

    def _fail(
        self, reason: str, elapsed: float,
    ) -> dict[str, Any]:
        return {
            "status": "error",
            "data": None,
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(),
                ),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": reason,
        }


def _status_next_action() -> str:
    """Pick the next action operator should take based on the
    current platform readiness state."""
    statuses = get_all_status()
    ready = [p for p, s in statuses.items() if s.ready]
    if ready:
        return (
            f"Platforms ready: {', '.join(ready)}. Launch "
            "first campaign: shopai ads launch --platform "
            f"{ready[0]} --budget-daily 10"
        )
    return (
        "No platforms ready. Connect Meta: shopai ads connect "
        "meta --token <ACCESS_TOKEN> --account-id <ACT_ID>"
    )
