"""Security Monitor Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Access Logs/Config -> Threat Scanner -> Vulnerability Checker ->
  Access Auditor -> Incident Reporter -> Output

Engine contract:
  Input:  {status, data: {access_logs, configurations, known_vulnerabilities}, meta, error}
  Output: {status, data: {threats, vulnerabilities, suspicious_access, incidents, risk_score}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .threat_scanner import scan_threats
from .vulnerability_checker import check_vulnerabilities
from .access_auditor import audit_access
from .incident_reporter import report_incidents


class SecurityMonitorEngine:
    """Security Monitor Engine — orchestrator only, no logic."""

    ENGINE_NAME = "security_monitor"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full security monitoring pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            Security monitoring output dict.
        """
        start = time.monotonic()

        # ---- Stage 0: Input validation (no mutation) ----
        try:
            payload = copy.deepcopy(input_payload)
        except Exception as exc:
            return self._fail(f"Input copy failed: {exc}", 0.0)

        if not isinstance(payload, dict):
            return self._fail("Input must be a dict", 0.0)

        if payload.get("status") == "fail":
            return self._fail(
                payload.get("error", "Upstream failure"), 0.0,
            )

        data = payload.get("data", {})
        if not isinstance(data, dict):
            return self._fail("Input 'data' must be a dict", 0.0)

        access_logs = data.get("access_logs", [])
        configurations = data.get("configurations", {})
        known_vulnerabilities = data.get("known_vulnerabilities", [])

        if not access_logs and not configurations:
            return self._fail("Access logs or configurations required", 0.0)

        # ---- Stage 1: Threat Scanner ----
        threat_result = scan_threats(access_logs=access_logs)
        if threat_result.get("status") == "error":
            return self._fail(
                f"Threat scanning failed: {threat_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        threats = threat_result.get("threats", [])

        # ---- Stage 2: Vulnerability Checker ----
        vuln_result = check_vulnerabilities(
            configurations=configurations,
            known_vulnerabilities=known_vulnerabilities,
        )
        if vuln_result.get("status") == "error":
            return self._fail(
                f"Vulnerability check failed: {vuln_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        vulnerabilities = vuln_result.get("vulnerabilities", [])

        # ---- Stage 3: Access Auditor ----
        access_result = audit_access(access_logs=access_logs)
        if access_result.get("status") == "error":
            return self._fail(
                f"Access audit failed: {access_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        suspicious_access = access_result.get("suspicious_access", [])

        # ---- Stage 4: Incident Reporter ----
        incident_result = report_incidents(
            threats=threats,
            vulnerabilities=vulnerabilities,
            suspicious_access=suspicious_access,
        )
        if incident_result.get("status") == "error":
            return self._fail(
                f"Incident reporting failed: {incident_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        incidents = incident_result.get("incidents", [])
        risk_score = incident_result.get("risk_score", 0.0)

        # ---- Stage 5: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "threats": threats,
                "vulnerabilities": vulnerabilities,
                "suspicious_access": suspicious_access,
                "incidents": incidents,
                "risk_score": risk_score,
            },
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": None,
        }

    # -------------------------------------------------------------------
    # Error output
    # -------------------------------------------------------------------

    def _fail(self, reason: str, elapsed: float) -> dict[str, Any]:
        """Return a standardized failure output."""
        return {
            "status": "error",
            "data": None,
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": reason,
        }
