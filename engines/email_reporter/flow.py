"""Email Reporter Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.

Pipeline:
  Input → Memory Reader → Report Compiler → Template Renderer →
  Schedule Manager → Recipient Manager → Memory Writer → Output

Engine contract:
  Input:  {status, data: {report_type, recipients, data}, meta, error}
  Output: {status, data: {report, schedule, recipients, delivery_status}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .report_compiler import compile_report
from .template_renderer import render_template
from .schedule_manager import manage_schedule
from .recipient_manager import manage_recipients
from .memory_reader import read_past_reports
from .memory_writer import write_report_result


class EmailReporterEngine:
    """Email Reporter Engine — orchestrator only, no logic."""

    ENGINE_NAME = "email_reporter"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        start = time.monotonic()

        try:
            payload = copy.deepcopy(input_payload)
        except Exception as exc:
            return self._fail(f"Input copy failed: {exc}", 0.0)

        if not isinstance(payload, dict):
            return self._fail("Input must be a dict", 0.0)
        if payload.get("status") == "fail":
            return self._fail(payload.get("error", "Upstream failure"), 0.0)

        data = payload.get("data", {})
        if not isinstance(data, dict):
            return self._fail("Input 'data' must be a dict", 0.0)

        report_type = str(data.get("report_type", "weekly"))
        recipients = data.get("recipients", [])
        report_data = data.get("data", {})

        if report_type not in ("daily", "weekly", "monthly"):
            return self._fail(f"Invalid report_type: {report_type}. Must be daily, weekly, or monthly.", 0.0)
        if not recipients:
            return self._fail("At least one recipient is required", 0.0)

        # ---- Stage 1: Memory Reader ----
        _past = read_past_reports(limit=5)

        # ---- Stage 2: Report Compiler ----
        compile_result = compile_report(report_type=report_type, data=report_data)
        if compile_result.get("status") == "error":
            return self._fail(f"Report compilation failed: {compile_result.get('error', 'unknown')}", time.monotonic() - start)
        compiled_report = compile_result.get("compiled_report", {})

        # ---- Stage 3: Template Renderer ----
        render_result = render_template(compiled_report=compiled_report)
        if render_result.get("status") == "error":
            return self._fail(f"Template rendering failed: {render_result.get('error', 'unknown')}", time.monotonic() - start)
        rendered = render_result.get("rendered", {})

        # ---- Stage 4: Schedule Manager ----
        schedule_result = manage_schedule(report_type=report_type)
        if schedule_result.get("status") == "error":
            return self._fail(f"Schedule management failed: {schedule_result.get('error', 'unknown')}", time.monotonic() - start)
        schedule = schedule_result.get("schedule", {})

        # ---- Stage 5: Recipient Manager ----
        recipient_result = manage_recipients(recipients=recipients)
        if recipient_result.get("status") == "error":
            return self._fail(f"Recipient management failed: {recipient_result.get('error', 'unknown')}", time.monotonic() - start)
        recipient_list = recipient_result.get("recipient_list", {})

        # ---- Stage 6: Memory Writer (non-fatal) ----
        subject = rendered.get("subject", "Report")
        _write = write_report_result(
            subject=subject,
            recipients_count=recipient_list.get("valid_count", 0),
            report_type=report_type,
        )

        # ---- Stage 7: Assemble output ----
        delivery_status = "queued" if recipient_list.get("valid_count", 0) > 0 else "no_valid_recipients"

        elapsed = time.monotonic() - start
        return {
            "status": "success",
            "data": {
                "report": {
                    "subject": rendered.get("subject", ""),
                    "html_content": rendered.get("html_content", ""),
                    "text_content": rendered.get("text_content", ""),
                },
                "schedule": schedule,
                "recipients": recipient_list,
                "delivery_status": delivery_status,
            },
            "meta": {"engine": self.ENGINE_NAME, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "elapsed_seconds": round(elapsed, 3)},
            "error": None,
        }

    def _fail(self, reason: str, elapsed: float) -> dict[str, Any]:
        return {
            "status": "error", "data": None,
            "meta": {"engine": self.ENGINE_NAME, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "elapsed_seconds": round(elapsed, 3)},
            "error": reason,
        }
