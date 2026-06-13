"""Review Request Engine — Pattern Q envelope.

Wraps the sender + tracking modules in the canonical
{status, data, meta, error} shape. Actions:

  status      -- ESP wiring + asked-so-far totals
  preview     -- show next N candidate requests (no send)
  send-batch  -- build + dispatch (commits)
"""
from __future__ import annotations

import copy
import logging
import time
from dataclasses import asdict
from typing import Any

from .sender import BatchReport, build_batch, send_batch
from .tracking import asked_count

logger = logging.getLogger(__name__)


class ReviewRequestEngine:
    ENGINE_NAME = "review_request"

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
            return self._success(
                self._status_payload(data),
                start,
            )

        if action == "preview":
            return self._success(
                self._preview_payload(data),
                start,
            )

        if action == "send-batch":
            return self._success(
                self._send_payload(data),
                start,
            )

        return self._fail(
            f"unknown action '{action}'. Use status / "
            "preview / send-batch.",
            time.monotonic() - start,
        )

    # ── Action handlers ───────────────────────────────────

    def _status_payload(
        self, data: dict[str, Any],
    ) -> dict[str, Any]:
        esp_ready = _esp_configured()
        count = asked_count()
        return {
            "action": "status",
            "esp_ready": esp_ready,
            "asked_so_far": count,
            "next_action": _status_next_action(esp_ready, count),
        }

    def _preview_payload(
        self, data: dict[str, Any],
    ) -> dict[str, Any]:
        report = build_batch(
            limit=int(data.get("limit", 5)),
            window_days=float(data.get("window_days", 14)),
            niche=data.get("niche"),
            store_name=data.get("store_name"),
            review_link_template=data.get(
                "review_link_template",
            ),
        )
        return {
            "action": "preview",
            "report": _report_summary(report),
            "requests": [
                {
                    "order_id": r.order_id,
                    "customer_email": r.customer_email,
                    "customer_name": r.customer_name,
                    "product_title": r.product_title,
                    "subject": r.subject,
                }
                for r in report.requests
            ],
            "next_action": _preview_next_action(report),
        }

    def _send_payload(
        self, data: dict[str, Any],
    ) -> dict[str, Any]:
        report = send_batch(
            limit=int(data.get("limit", 5)),
            window_days=float(data.get("window_days", 14)),
            niche=data.get("niche"),
            store_name=data.get("store_name"),
            review_link_template=data.get(
                "review_link_template",
            ),
            from_email=data.get("from_email"),
        )
        return {
            "action": "send-batch",
            "report": _report_summary(report),
            "next_action": _send_next_action(report),
        }

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


def _esp_configured() -> bool:
    """Cheap heuristic: an ESP env var is set."""
    import os
    for env in (
        "BREVO_API_KEY",
        "RESEND_API_KEY",
        "SENDGRID_API_KEY",
        "MAILGUN_API_KEY",
    ):
        if os.environ.get(env):
            return True
    return False


def _report_summary(report: BatchReport) -> dict[str, Any]:
    return {
        "eligible": report.eligible,
        "already_asked": report.already_asked,
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
            "shopai reviews preview --limit 5"
        )
    return (
        f"ESP ready. {count} ask(s) recorded. "
        "shopai reviews preview to see what's next."
    )


def _preview_next_action(report: BatchReport) -> str:
    if report.queued == 0:
        if report.eligible == 0:
            return (
                "No eligible orders in window. Widen with "
                "--window-days 30 or wait for deliveries."
            )
        return (
            f"{report.eligible} eligible but all already "
            "asked. Wait for more deliveries."
        )
    return (
        f"{report.queued} ready to send. Commit with: "
        "shopai reviews send-batch --yes"
    )


def _send_next_action(report: BatchReport) -> str:
    if report.queued == 0:
        return (
            "Nothing to send. Run preview first: "
            "shopai reviews preview"
        )
    if report.failed == 0:
        return (
            f"Sent {report.sent} review request(s). "
            "Next batch: shopai reviews preview"
        )
    return (
        f"Sent {report.sent}, failed {report.failed}. "
        "Check ESP status: shopai email status"
    )
