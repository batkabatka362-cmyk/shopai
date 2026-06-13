"""Autonomy summarizer (W303): operator-shareable one-paragraph
state digest.

`shopai autonomy-status` / `autonomy-doctor` / `autonomy-smoke`
each render structured operator output. autonomy-summarize
collapses the three into ONE paragraph of plain text suitable
for paste into Slack, an ops handoff doc, or an LLM prompt
asking "what's the state of the autonomy substrate".

Distinct from `shopai empire --summarize` which spans the whole
business; this is autonomy-substrate specific.

Output shape (single paragraph, ~200-400 chars):

  "Autonomy substrate is HEALTHY across 7 domains: 7/7 doctor
   ok, 7/7 smoke ok, 0 paused, 0 degraded. Last 7d: 0 applied
   actions, 0 alerts. Env: 4 of 43 knobs set. Wiring nominal."

When there are issues, the paragraph shifts to call them out:

  "Autonomy substrate has 2 ISSUES: marketing domain paused
   (budget cap breach), refund domain degraded (adapter
   failure ratio 27%). 5 of 7 domains nominal. Drill: shopai
   autonomy-doctor + marketing-resume."
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class AutonomySummary:
    text: str
    overall_cls: str  # ok / warn / fail
    has_issues: bool


def _doctor_block() -> dict[str, Any]:
    try:
        from core.automation.autonomy_doctor import (
            run_autonomy_doctor,
        )
        r = run_autonomy_doctor()
        return {
            "ok": r.ok_count,
            "warn": r.warn_count,
            "fail": r.fail_count,
            "total": len(r.domains),
            "fail_domains": [
                d.name for d in r.domains if d.cls == "fail"
            ],
            "warn_domains": [
                d.name for d in r.domains if d.cls == "warn"
            ],
            "next_action": r.overall_next_action,
        }
    except Exception:  # noqa: BLE001
        return {}


def _smoke_block() -> dict[str, Any]:
    try:
        from core.automation.autonomy_smoke import (
            run_autonomy_smoke,
        )
        r = run_autonomy_smoke()
        return {
            "ok": r.ok_count,
            "error": r.error_count,
            "total": len(r.domains),
            "error_domains": [
                d.domain for d in r.domains if d.cls == "error"
            ],
        }
    except Exception:  # noqa: BLE001
        return {}


def _status_block() -> dict[str, Any]:
    try:
        from core.automation.autonomy_status import (
            get_autonomy_status,
        )
        r = get_autonomy_status()
        return {
            "verdict": r.overall_verdict,
            "applied": r.total_applied,
            "paused_domains": list(r.paused_domains),
            "domain_count": len(r.domains),
        }
    except Exception:  # noqa: BLE001
        return {}


def _env_block() -> dict[str, Any]:
    try:
        from engines._pattern_t_audit import (
            build_autonomy_env_registry,
        )
        r = build_autonomy_env_registry()
        return {
            "set": r.set_count,
            "total": r.total_knobs,
        }
    except Exception:  # noqa: BLE001
        return {}


def _classify(
    doctor: dict, smoke: dict, status: dict,
) -> str:
    """Decide overall class from blocks."""
    if doctor.get("fail", 0) > 0:
        return "fail"
    if smoke.get("error", 0) > 0:
        return "fail"
    if doctor.get("warn", 0) > 0:
        return "warn"
    if status.get("paused_domains"):
        return "warn"
    if status.get("verdict") in ("degraded", "critical"):
        return "warn"
    return "ok"


def _render_text(
    cls: str,
    doctor: dict,
    smoke: dict,
    status: dict,
    env: dict,
) -> str:
    """Build the one-paragraph summary text."""
    total = doctor.get("total") or 7
    parts: list[str] = []
    # Headline (no trailing colon -- the joiner already uses ", ")
    if cls == "ok":
        parts.append(
            f"Autonomy substrate is HEALTHY across {total} "
            "domains"
        )
    elif cls == "warn":
        warn_count = (
            doctor.get("warn", 0)
            + len(status.get("paused_domains", []))
        )
        parts.append(
            f"Autonomy substrate has {warn_count} ISSUE(S)"
        )
    else:
        fail_count = (
            doctor.get("fail", 0) + smoke.get("error", 0)
        )
        parts.append(
            f"Autonomy substrate is BROKEN ({fail_count} "
            "failure(s))"
        )

    # Doctor + smoke numbers
    if doctor:
        parts.append(
            f"{doctor.get('ok', 0)}/{total} doctor ok"
        )
    if smoke:
        parts.append(
            f"{smoke.get('ok', 0)}/{smoke.get('total', total)} "
            "smoke ok"
        )

    # Activity + alerts
    if status:
        paused = status.get("paused_domains", [])
        if paused:
            parts.append(
                f"paused: {', '.join(paused)}"
            )
        applied = status.get("applied", 0)
        parts.append(f"last 7d: {applied} applied")

    # Env coverage
    if env:
        parts.append(
            f"env {env.get('set', 0)} of "
            f"{env.get('total', 0)} knobs set"
        )

    # Drill hint
    if cls != "ok":
        if doctor.get("fail_domains"):
            parts.append(
                f"FAILING: {', '.join(doctor['fail_domains'])}"
            )
        if smoke.get("error_domains"):
            parts.append(
                "smoke errors: "
                f"{', '.join(smoke['error_domains'])}"
            )
        parts.append("drill: shopai autonomy-doctor")

    return ", ".join(parts) + "."


def run_autonomy_summarize() -> AutonomySummary:
    """Generate the one-paragraph autonomy substrate summary."""
    doctor = _doctor_block()
    smoke = _smoke_block()
    status = _status_block()
    env = _env_block()
    cls = _classify(doctor, smoke, status)
    text = _render_text(cls, doctor, smoke, status, env)
    return AutonomySummary(
        text=text,
        overall_cls=cls,
        has_issues=(cls != "ok"),
    )
