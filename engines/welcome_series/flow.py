"""Welcome Series Engine — Pattern Q envelope.

Actions: status / preview / send-batch.
"""
from __future__ import annotations

import copy
import logging
import os
import time
from typing import Any

from .sender import WelcomeBatchReport, build_batch, send_batch
from .tracking import welcomed_count

logger = logging.getLogger(__name__)


class WelcomeSeriesEngine:
    ENGINE_NAME = "welcome_series"

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
        action = str(data.get("action") or "status").lower()

        if action == "status":
            esp_ready = _esp_configured()
            count = welcomed_count()
            return self._success(
                {
                    "action": "status",
                    "esp_ready": esp_ready,
                    "welcomed_so_far": count,
                    "next_action": _status_next_action(
                        esp_ready, count,
                    ),
                },
                start,
            )

        if action == "preview":
            report = build_batch(
                limit=int(data.get("limit", 5)),
                store_name=data.get("store_name"),
                discount_code=data.get("discount_code"),
                shop_url=data.get("shop_url"),
            )
            return self._success(
                {
                    "action": "preview",
                    "report": _report_summary(report),
                    "requests": [
                        {
                            "customer_id": r.customer_id,
                            "customer_email": r.customer_email,
                            "customer_name": r.customer_name,
                            "stage": r.stage,
                            "subject": r.subject,
                        }
                        for r in report.requests
                    ],
                    "next_action": _preview_next_action(report),
                },
                start,
            )

        if action == "send-batch":
            report = send_batch(
                limit=int(data.get("limit", 5)),
                store_name=data.get("store_name"),
                discount_code=data.get("discount_code"),
                shop_url=data.get("shop_url"),
                from_email=data.get("from_email"),
            )
            return self._success(
                {
                    "action": "send-batch",
                    "report": _report_summary(report),
                    "next_action": _send_next_action(report),
                },
                start,
            )

        return self._fail(
            f"unknown action '{action}'. Use status / "
            "preview / send-batch.",
            time.monotonic() - start,
        )

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


def _esp_configured() -> bool:
    for env in (
        "BREVO_API_KEY",
        "RESEND_API_KEY",
        "SENDGRID_API_KEY",
        "MAILGUN_API_KEY",
    ):
        if os.environ.get(env):
            return True
    return False


def _report_summary(report: WelcomeBatchReport) -> dict[str, Any]:
    return {
        "eligible": report.eligible,
        "already_completed": report.already_completed,
        "not_due_yet": report.not_due_yet,
        "queued": report.queued,
        "sent": report.sent,
        "failed": report.failed,
        "skipped_reasons": dict(report.skipped_reasons),
    }


def _status_next_action(esp_ready: bool, count: int) -> str:
    if not esp_ready:
        return (
            "No ESP wired. Run: shopai email connect "
            "--provider brevo --api-key KEY"
        )
    if count == 0:
        return (
            "ESP ready. Preview the batch: "
            "shopai welcome preview --limit 5"
        )
    return (
        f"ESP ready. {count} customer(s) welcomed so far. "
        "shopai welcome preview to see next batch."
    )


def _preview_next_action(report: WelcomeBatchReport) -> str:
    if report.queued == 0:
        if report.eligible == 0:
            return (
                "No eligible customers right now. New "
                "registrations or expired cadence gates will "
                "appear here."
            )
        return f"{report.eligible} eligible queued."
    return (
        f"{report.queued} ready to send. Commit with: "
        "shopai welcome send-batch --yes"
    )


def _send_next_action(report: WelcomeBatchReport) -> str:
    if report.queued == 0:
        return (
            "Nothing to send. Run preview first: "
            "shopai welcome preview"
        )
    if report.failed == 0:
        return (
            f"Sent {report.sent} welcome email(s). "
            "Next: shopai welcome preview"
        )
    return (
        f"Sent {report.sent}, failed {report.failed}. "
        "Check ESP: shopai email status"
    )
