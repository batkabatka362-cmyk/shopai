"""Go-live readiness gate — the single-verb pre-T1 check.

Runs through every prerequisite the owner's T1_GO_LIVE.md
checklist covers + emits a single verdict: READY / BLOCKED.
Owner types one command (``shopai ready-for-live``) and sees
either "go" or a numbered list of specific things to fix.

Checks (deterministic order):
  1. env — SHOPAI_SHOPIFY_URL + key present?
  2. doctor probes — shopify + meta + vault
  3. learning loop — can we replay 5 synthetic orders without
     crash + feedback_store records them?
  4. live-health — verdict ``healthy`` or ``unknown``
     (unknown = OK for fresh setup, no cycles yet)
  5. live_execution gate — currently off? (§4b.G paranoid mode:
     owner must flip on *after* this gate passes)

Each check returns ``(ok, short_reason, fix)``. Gate returns
overall verdict + the ordered list.

Pure stdlib. Dependency-injected runners for tests.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CheckResult:
    name: str
    ok: bool
    reason: str = ""
    fix: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "reason": self.reason,
            "fix": self.fix,
        }


@dataclass
class GoLiveReport:
    verdict: str  # "READY" | "BLOCKED"
    checks: list[CheckResult] = field(default_factory=list)

    def blocking(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.ok]

    def as_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "checks": [c.as_dict() for c in self.checks],
            "blocking": [
                c.as_dict() for c in self.blocking()
            ],
        }


def _check_env() -> CheckResult:
    url = os.environ.get("SHOPAI_SHOPIFY_URL", "").strip()
    # Either OAuth key OR classic admin token is acceptable
    key = (
        os.environ.get("SHOPAI_SHOPIFY_KEY", "").strip()
        or os.environ.get(
            "SHOPAI_SHOPIFY_CLIENT_SECRET", "",
        ).strip()
    )
    if not url or not key:
        missing = []
        if not url:
            missing.append("SHOPAI_SHOPIFY_URL")
        if not key:
            missing.append(
                "SHOPAI_SHOPIFY_KEY (or OAuth creds)",
            )
        # Concrete export lines so the owner can copy-paste
        # rather than guess the format.
        export_hint = []
        if not url:
            export_hint.append(
                "  export SHOPAI_SHOPIFY_URL="
                "your-store.myshopify.com",
            )
        if not key:
            export_hint.append(
                "  export SHOPAI_SHOPIFY_KEY=shpat_xxx",
            )
        return CheckResult(
            name="env",
            ok=False,
            reason=f"missing {', '.join(missing)}",
            fix=(
                "Add to .env or export inline:\n"
                + "\n".join(export_hint)
                + "\nFull list: docs/T1_GO_LIVE.md §1"
            ),
        )
    return CheckResult(
        name="env",
        ok=True,
        reason="Shopify credentials present",
    )


def _check_doctor(doctor_runner: Any = None) -> CheckResult:
    try:
        if doctor_runner is None:
            from core.readiness.doctor import run as _run
            report = _run()
        else:
            report = doctor_runner()
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name="doctor",
            ok=False,
            reason=f"doctor raised: {exc}",
            fix="run `shopai doctor --json` to debug",
        )
    crit = int(getattr(report, "critical_failures", 0))
    if crit > 0:
        return CheckResult(
            name="doctor",
            ok=False,
            reason=(
                f"{crit} critical probe failures"
            ),
            fix=(
                "run `shopai doctor` → see fix field of "
                "each failing probe"
            ),
        )
    return CheckResult(
        name="doctor",
        ok=True,
        reason="all critical probes green",
    )


def _check_learning_loop() -> CheckResult:
    """Replay 5 synthetic orders + verify feedback_store
    records them. Validates the webhook → Deliberation →
    engine bus → feedback_store chain fires end-to-end."""
    try:
        from agents.replay.synthesize import (
            synthesize_orders_with_random_decisions,
        )
        from agents.replay.order_replay import replay_orders
        from core.learning.feedback_store import (
            get_feedback_store,
        )
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name="learning_loop",
            ok=False,
            reason=f"import failed: {exc}",
            fix="PYTHONPATH=. must include the repo root",
        )
    try:
        orders = synthesize_orders_with_random_decisions(
            count=5, seed=7,
        )
        before = sum(
            int(v.get("total_runs", 0))
            for v in get_feedback_store().get_all_stats(
            ).values()
        )
        stats = replay_orders(orders)
        after = sum(
            int(v.get("total_runs", 0))
            for v in get_feedback_store().get_all_stats(
            ).values()
        )
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name="learning_loop",
            ok=False,
            reason=f"replay raised: {exc}",
            fix=(
                "run `shopai replay-orders --synthesize 5` "
                "directly to reproduce"
            ),
        )
    if stats.failed > 0:
        return CheckResult(
            name="learning_loop",
            ok=False,
            reason=(
                f"{stats.failed}/5 synthetic orders failed "
                "in the webhook handler"
            ),
            fix=(
                "check logs — a handler exception likely "
                "surfaced; run `shopai replay-orders "
                "--synthesize 5 --json` for details"
            ),
        )
    if after <= before:
        return CheckResult(
            name="learning_loop",
            ok=False,
            reason=(
                "feedback_store did not accumulate from "
                "the replay (engine_outcome_bus wiring "
                "may be broken)"
            ),
            fix=(
                "inspect core/webhooks/order_handler.py "
                "step 4c + engine_outcome_bus sinks"
            ),
        )
    return CheckResult(
        name="learning_loop",
        ok=True,
        reason=(
            f"5 synthetic orders → "
            f"{after - before} feedback entries"
        ),
    )


def _check_live_health(
    live_health_runner: Any = None,
) -> CheckResult:
    try:
        if live_health_runner is None:
            from core.readiness.health_trend import (
                compute_live_health,
            )
            trend = compute_live_health()
        else:
            trend = live_health_runner()
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name="live_health",
            ok=False,
            reason=f"health trend raised: {exc}",
            fix="run `shopai live-health` directly",
        )
    verdict = str(getattr(trend, "verdict", ""))
    if verdict in ("healthy", "unknown"):
        return CheckResult(
            name="live_health",
            ok=True,
            reason=(
                f"verdict={verdict} — ok for pre-T1"
            ),
        )
    return CheckResult(
        name="live_health",
        ok=False,
        reason=f"verdict={verdict}",
        fix=(
            "run `shopai live-health` — inspect reasons; "
            "fix declining engines / cycle errors before "
            "going live"
        ),
    )


def _check_live_gate_off() -> CheckResult:
    """§4b.G paranoid mode — live-execution env var should be
    OFF when the owner runs this gate. They flip it on AFTER
    a clean report. If it's already on, the gate still passes
    but warns."""
    from core.system.live_execution import (
        is_live_execution_enabled,
    )
    enabled = is_live_execution_enabled()
    if enabled:
        return CheckResult(
            name="live_gate",
            ok=True,
            reason=(
                "live execution already enabled — assume "
                "T1 is running"
            ),
        )
    return CheckResult(
        name="live_gate",
        ok=True,
        reason=(
            "live execution disabled (expected pre-T1)"
        ),
    )


def run_go_live_gate(
    *,
    doctor_runner: Any = None,
    live_health_runner: Any = None,
    skip_learning_loop: bool = False,
) -> GoLiveReport:
    """Run every check in order, return a single verdict.

    ``doctor_runner`` / ``live_health_runner`` are test seams.
    ``skip_learning_loop`` is an opt-out for environments
    where synthetic replay is too expensive or the real
    autopilot daemon is already running (replay spam would
    interfere with live cycle state).
    """
    checks: list[CheckResult] = []
    checks.append(_check_env())
    checks.append(_check_doctor(doctor_runner=doctor_runner))
    if not skip_learning_loop:
        checks.append(_check_learning_loop())
    checks.append(_check_live_health(
        live_health_runner=live_health_runner,
    ))
    checks.append(_check_live_gate_off())
    verdict = "READY" if all(c.ok for c in checks) else "BLOCKED"
    return GoLiveReport(verdict=verdict, checks=checks)
