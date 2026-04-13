"""Security Monitor Engine — access auditor.

Audits access patterns for anomalies: unusual login times, geographic
anomalies, privilege escalation, and suspicious admin actions.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Anomaly thresholds
# ---------------------------------------------------------------------------

_UNUSUAL_HOUR_START = 0      # Midnight
_UNUSUAL_HOUR_END = 5        # 5 AM
_MAX_FAILED_ATTEMPTS = 5     # Per user in window
_GEO_DISTANCE_THRESHOLD = 2  # Different countries in short time


def audit_access(
    access_logs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Audit access patterns for suspicious behavior.

    Analyzes login patterns, geographic consistency, and admin
    actions for anomalies.

    Args:
        access_logs: List of access log dicts with user_id, ip, timestamp,
            action, success, country, role fields.

    Returns:
        Structured dict with suspicious_access list.
    """
    try:
        logs = copy.deepcopy(access_logs)
        suspicious: list[dict[str, Any]] = []

        if not logs:
            return {
                "status": "success",
                "suspicious_access": [],
                "total_suspicious": 0,
            }

        # Group by user
        user_logs: dict[str, list[dict[str, Any]]] = {}
        for log in logs:
            uid = str(log.get("user_id", "unknown"))
            user_logs.setdefault(uid, []).append(log)

        for uid, user_entries in user_logs.items():
            # Sort by timestamp
            user_entries.sort(key=lambda e: float(e.get("timestamp", 0)))

            # --- Failed login attempts ---
            failed = [e for e in user_entries if not e.get("success", True)]
            if len(failed) > _MAX_FAILED_ATTEMPTS:
                suspicious.append({
                    "type": "excessive_failed_logins",
                    "severity": "high",
                    "user_id": uid,
                    "detail": (
                        f"User '{uid}' had {len(failed)} failed login attempts."
                    ),
                    "evidence_count": len(failed),
                })

            # --- Unusual hour access ---
            for entry in user_entries:
                ts = float(entry.get("timestamp", 0))
                # Extract hour (rough: use modular arithmetic on unix timestamp)
                hour = int((ts % 86400) / 3600)
                if _UNUSUAL_HOUR_START <= hour < _UNUSUAL_HOUR_END:
                    action = str(entry.get("action", ""))
                    role = str(entry.get("role", ""))
                    if role in ("admin", "superadmin"):
                        suspicious.append({
                            "type": "unusual_hour_admin_access",
                            "severity": "medium",
                            "user_id": uid,
                            "detail": (
                                f"Admin user '{uid}' accessed '{action}' "
                                f"at unusual hour ({hour}:00 UTC)."
                            ),
                            "evidence_count": 1,
                        })
                        break  # one alert per user

            # --- Geographic anomaly ---
            countries = []
            for entry in user_entries:
                country = str(entry.get("country", ""))
                if country and (not countries or countries[-1] != country):
                    countries.append(country)

            if len(set(countries)) >= _GEO_DISTANCE_THRESHOLD:
                suspicious.append({
                    "type": "geographic_anomaly",
                    "severity": "high",
                    "user_id": uid,
                    "detail": (
                        f"User '{uid}' accessed from {len(set(countries))} "
                        f"different countries: {', '.join(set(countries))}."
                    ),
                    "evidence_count": len(set(countries)),
                })

            # --- Privilege escalation ---
            roles_seen: list[str] = []
            for entry in user_entries:
                role = str(entry.get("role", ""))
                if role and (not roles_seen or roles_seen[-1] != role):
                    roles_seen.append(role)

            role_order = {"viewer": 0, "editor": 1, "admin": 2, "superadmin": 3}
            for i in range(len(roles_seen) - 1):
                curr_level = role_order.get(roles_seen[i], 0)
                next_level = role_order.get(roles_seen[i + 1], 0)
                if next_level > curr_level + 1:
                    suspicious.append({
                        "type": "privilege_escalation",
                        "severity": "critical",
                        "user_id": uid,
                        "detail": (
                            f"User '{uid}' role jumped from "
                            f"'{roles_seen[i]}' to '{roles_seen[i+1]}'."
                        ),
                        "evidence_count": 1,
                    })
                    break

        # Sort by severity
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        suspicious.sort(
            key=lambda s: severity_order.get(s.get("severity", "low"), 4),
        )

        return {
            "status": "success",
            "suspicious_access": suspicious,
            "total_suspicious": len(suspicious),
        }
    except Exception as exc:
        return {
            "status": "error",
            "suspicious_access": [],
            "error": f"Access audit failed: {exc}",
        }
