"""Security Monitor Engine — threat scanner.

Scans for common security threats by analyzing access logs and
configuration patterns. Detects brute force, injection attempts,
and suspicious request patterns.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Threat detection patterns
# ---------------------------------------------------------------------------

_BRUTE_FORCE_THRESHOLD = 10   # >10 failed logins from same IP in window
_RATE_LIMIT_THRESHOLD = 100   # >100 requests/min from same IP
_SUSPICIOUS_PATHS = {
    "/wp-admin", "/wp-login", "/.env", "/config", "/admin/config",
    "/phpmyadmin", "/.git", "/backup", "/db", "/sql",
}
_INJECTION_PATTERNS = {
    "SELECT ", "UNION ", "DROP ", "INSERT ", "DELETE ",
    "<script", "javascript:", "onerror=", "onload=",
    "../", "..\\", "%2e%2e",
}


def scan_threats(
    access_logs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Scan access logs for common security threats.

    Analyzes request patterns for brute force attacks, injection
    attempts, suspicious path probing, and rate limit violations.

    Args:
        access_logs: List of log dicts with ip, path, method, status_code,
            timestamp, user_agent, query_string fields.

    Returns:
        Structured dict with threats list.
    """
    try:
        logs = copy.deepcopy(access_logs)
        threats: list[dict[str, Any]] = []

        if not logs:
            return {
                "status": "success",
                "threats": [],
                "total_threats": 0,
            }

        # Group by IP
        ip_requests: dict[str, list[dict[str, Any]]] = {}
        for log in logs:
            ip = str(log.get("ip", "unknown"))
            ip_requests.setdefault(ip, []).append(log)

        for ip, requests in ip_requests.items():
            # --- Brute force detection ---
            failed_logins = [
                r for r in requests
                if (
                    int(r.get("status_code", 200)) == 401
                    or int(r.get("status_code", 200)) == 403
                )
                and str(r.get("path", "")).lower() in ("/login", "/auth", "/api/auth", "/admin")
            ]
            if len(failed_logins) > _BRUTE_FORCE_THRESHOLD:
                threats.append({
                    "type": "brute_force",
                    "severity": "critical" if len(failed_logins) > 50 else "high",
                    "source_ip": ip,
                    "details": (
                        f"{len(failed_logins)} failed login attempts from {ip}."
                    ),
                    "evidence_count": len(failed_logins),
                })

            # --- Rate limit violation ---
            if len(requests) > _RATE_LIMIT_THRESHOLD:
                threats.append({
                    "type": "rate_limit_violation",
                    "severity": "medium",
                    "source_ip": ip,
                    "details": (
                        f"{len(requests)} requests from {ip} "
                        f"(threshold: {_RATE_LIMIT_THRESHOLD})."
                    ),
                    "evidence_count": len(requests),
                })

            # --- Suspicious path probing ---
            suspicious_hits = [
                r for r in requests
                if any(
                    sp in str(r.get("path", "")).lower()
                    for sp in _SUSPICIOUS_PATHS
                )
            ]
            if suspicious_hits:
                paths_hit = list({str(r.get("path", "")) for r in suspicious_hits})
                threats.append({
                    "type": "path_probing",
                    "severity": "high" if len(suspicious_hits) > 5 else "medium",
                    "source_ip": ip,
                    "details": (
                        f"Suspicious path probing from {ip}: "
                        f"{', '.join(paths_hit[:5])}."
                    ),
                    "evidence_count": len(suspicious_hits),
                })

            # --- Injection attempts ---
            for req in requests:
                query = str(req.get("query_string", "")).upper()
                path = str(req.get("path", "")).upper()
                combined = f"{path} {query}"

                injection_matches = [
                    p for p in _INJECTION_PATTERNS
                    if p.upper() in combined
                ]
                if injection_matches:
                    threats.append({
                        "type": "injection_attempt",
                        "severity": "critical",
                        "source_ip": ip,
                        "details": (
                            f"Possible injection attempt from {ip} "
                            f"on path '{req.get('path', '')}'. "
                            f"Patterns matched: {', '.join(injection_matches[:3])}."
                        ),
                        "evidence_count": len(injection_matches),
                    })
                    break  # one per IP is enough

        # Sort by severity
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        threats.sort(
            key=lambda t: severity_order.get(t.get("severity", "low"), 4),
        )

        return {
            "status": "success",
            "threats": threats,
            "total_threats": len(threats),
        }
    except Exception as exc:
        return {
            "status": "error",
            "threats": [],
            "error": f"Threat scanning failed: {exc}",
        }
