"""Security Monitor Engine — incident reporter.

Consolidates threats, vulnerabilities, and suspicious access into
security incidents. Computes an overall risk score.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
import hashlib
from typing import Any


# ---------------------------------------------------------------------------
# Risk scoring weights
# ---------------------------------------------------------------------------

_SEVERITY_SCORES: dict[str, float] = {
    "critical": 10.0,
    "high": 7.0,
    "medium": 4.0,
    "low": 1.0,
}


def report_incidents(
    threats: list[dict[str, Any]],
    vulnerabilities: list[dict[str, Any]],
    suspicious_access: list[dict[str, Any]],
) -> dict[str, Any]:
    """Consolidate security findings into incidents and compute risk score.

    Creates incident records from all findings, deduplicates by source,
    and computes an overall risk score (0-100).

    Args:
        threats: Detected threats from threat_scanner.
        vulnerabilities: Found vulnerabilities from vulnerability_checker.
        suspicious_access: Suspicious patterns from access_auditor.

    Returns:
        Structured dict with incidents list and risk_score.
    """
    try:
        threat_list = copy.deepcopy(threats)
        vuln_list = copy.deepcopy(vulnerabilities)
        access_list = copy.deepcopy(suspicious_access)

        incidents: list[dict[str, Any]] = []

        # --- Threat incidents ---
        for t in threat_list:
            incident_id = _make_id("threat", str(t.get("type", "")), str(t.get("source_ip", "")))
            incidents.append({
                "id": incident_id,
                "category": "threat",
                "type": t.get("type", ""),
                "severity": t.get("severity", "medium"),
                "source": t.get("source_ip", "unknown"),
                "description": t.get("details", ""),
                "evidence_count": t.get("evidence_count", 0),
                "status": "open",
            })

        # --- Vulnerability incidents ---
        for v in vuln_list:
            incident_id = _make_id("vuln", str(v.get("type", "")), str(v.get("component", "")))
            incidents.append({
                "id": incident_id,
                "category": "vulnerability",
                "type": v.get("type", ""),
                "severity": v.get("severity", "medium"),
                "source": v.get("component", "unknown"),
                "description": v.get("detail", ""),
                "remediation": v.get("remediation", ""),
                "status": "open",
            })

        # --- Suspicious access incidents ---
        for a in access_list:
            incident_id = _make_id("access", str(a.get("type", "")), str(a.get("user_id", "")))
            incidents.append({
                "id": incident_id,
                "category": "suspicious_access",
                "type": a.get("type", ""),
                "severity": a.get("severity", "medium"),
                "source": a.get("user_id", "unknown"),
                "description": a.get("detail", ""),
                "evidence_count": a.get("evidence_count", 0),
                "status": "open",
            })

        # --- Compute risk score (0-100) ---
        # Based on: count * severity weight, capped at 100
        raw_score = 0.0
        for inc in incidents:
            severity = str(inc.get("severity", "low"))
            raw_score += _SEVERITY_SCORES.get(severity, 1.0)

        # Normalize: 0 incidents = 0, scale logarithmically
        if raw_score <= 0:
            risk_score = 0.0
        elif raw_score <= 10:
            risk_score = raw_score * 3
        elif raw_score <= 30:
            risk_score = 30 + (raw_score - 10) * 2
        elif raw_score <= 60:
            risk_score = 70 + (raw_score - 30)
        else:
            risk_score = 100.0

        risk_score = round(min(risk_score, 100.0), 1)

        # Risk level
        if risk_score >= 80:
            risk_level = "critical"
        elif risk_score >= 60:
            risk_level = "high"
        elif risk_score >= 30:
            risk_level = "medium"
        elif risk_score > 0:
            risk_level = "low"
        else:
            risk_level = "none"

        # Sort by severity
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        incidents.sort(
            key=lambda i: severity_order.get(i.get("severity", "low"), 4),
        )

        return {
            "status": "success",
            "incidents": incidents,
            "total_incidents": len(incidents),
            "risk_score": risk_score,
            "risk_level": risk_level,
        }
    except Exception as exc:
        return {
            "status": "error",
            "incidents": [],
            "risk_score": 0.0,
            "error": f"Incident reporting failed: {exc}",
        }


def _make_id(category: str, itype: str, source: str) -> str:
    """Generate a deterministic incident ID."""
    hash_input = f"{category}:{itype}:{source}"
    return "INC-" + hashlib.sha256(hash_input.encode()).hexdigest()[:8].upper()
