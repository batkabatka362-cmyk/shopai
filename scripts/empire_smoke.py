"""Empire-AGI production smoke test — read-only verifier.

Walks the operator-visible empire-AGI surface against the LOCAL
approval queue + store manager. Reports pass / fail per step so
an operator on a fresh install can verify the wiring before
trusting the autonomous loop with real Shopify mutations.

No Shopify creds required. No queue writes. Each step calls
the canonical module-level entry point and reports:
  - PASS: returned the expected shape without raising
  - EMPTY: returned cleanly but no data (fresh install or no
    activity yet) -- not a failure, just a signal
  - FAIL: raised or returned malformed data

Output:
  - Text summary by default (one line per step + final pass count)
  - --json emits a structured report for automation

Usage:
    python scripts/empire_smoke.py
    python scripts/empire_smoke.py --json
    python scripts/empire_smoke.py --store <store_id>

Use case: run after deploying / upgrading ShopAI on a real
install to validate the empire-AGI commands work end-to-end
before relying on them. Companion to the
``docs/EMPIRE_AGI_WORKFLOW.md`` runbook.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import traceback
from dataclasses import asdict, dataclass

logger = logging.getLogger(__name__)

# Allow running as ``python scripts/empire_smoke.py`` from the
# repo root without an editable install.
_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)),
)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


@dataclass
class StepResult:
    name: str
    status: str  # PASS / EMPTY / FAIL
    detail: str = ""
    error: str | None = None


def _step_world_model_fleet() -> StepResult:
    """Verify per-store snapshots build via WorldModel."""
    try:
        from core.world_model import WorldModel
        from data_pipeline.store.store_manager import StoreManager

        sm = StoreManager()
        stores = sm.list_stores() or []
        if not stores:
            return StepResult(
                name="world-model fleet",
                status="EMPTY",
                detail="no stores registered yet",
            )
        wm = WorldModel(sm=sm)
        # Probe just the first store -- enough to verify wiring.
        sample = stores[0]
        sid = sample.get("store_id", "")
        snap = wm.snapshot(sid, skip_live=True)
        required = {
            "store_id", "fetched_at", "store", "stats", "sync",
            "approvals", "decisions", "transfers",
            "recent_outcomes",
        }
        missing = required - set(snap.keys())
        if missing:
            return StepResult(
                name="world-model fleet",
                status="FAIL",
                detail=f"snapshot missing sections: {sorted(missing)}",
            )
        return StepResult(
            name="world-model fleet",
            status="PASS",
            detail=(
                f"snapshot built for {sid!r} with all expected sections"
            ),
        )
    except Exception as exc:  # noqa: BLE001
        return StepResult(
            name="world-model fleet",
            status="FAIL",
            detail="raised during snapshot build",
            error=f"{type(exc).__name__}: {exc}",
        )


def _step_transfer_suggest_pipeline(
    target_store: str | None,
) -> StepResult:
    """Verify ApprovalQueue + transfer-suggest dependencies wire
    up. Doesn't require existing transfer rows -- a clean
    install returns EMPTY."""
    try:
        from core.approval.queue import (
            ApprovalStatus,
            get_approval_queue,
        )

        queue = get_approval_queue()
        # The transfer-suggest CLI uses list_by_status with
        # store_id kwarg (PR #239+). Verify the kwarg is
        # accepted.
        if target_store:
            executed = queue.list_by_status(
                ApprovalStatus.EXECUTED,
                store_id=target_store,
                limit=5,
            )
            return StepResult(
                name="transfer suggest pipeline",
                status="PASS" if executed else "EMPTY",
                detail=(
                    f"queue accepts store_id kwarg; "
                    f"{len(executed)} EXECUTED action(s) on "
                    f"{target_store!r}"
                ),
            )
        # No target -- just verify list_pending works
        pending = queue.list_pending(limit=5)
        return StepResult(
            name="transfer suggest pipeline",
            status="PASS" if pending else "EMPTY",
            detail=f"queue.list_pending returned {len(pending)} row(s)",
        )
    except TypeError as exc:
        return StepResult(
            name="transfer suggest pipeline",
            status="FAIL",
            detail="queue missing store_id support (needs PR #239)",
            error=f"{type(exc).__name__}: {exc}",
        )
    except Exception as exc:  # noqa: BLE001
        return StepResult(
            name="transfer suggest pipeline",
            status="FAIL",
            detail="raised during queue probe",
            error=f"{type(exc).__name__}: {exc}",
        )


def _step_engine_ranking() -> StepResult:
    """Verify the engine ranking analytics. EMPTY on fresh
    install is fine; FAIL indicates a wiring break."""
    try:
        from core.approval.outcome_aggregator import (
            aggregate_outcomes,  # noqa: F401  - import smoke
        )
        from core.approval.queue import get_approval_queue

        queue = get_approval_queue()
        # The CLI uses queue._conn directly for the engine
        # ranking scan. Verify the conn is present.
        if not hasattr(queue, "_conn"):
            return StepResult(
                name="engine ranking",
                status="FAIL",
                detail="queue lacks _conn attribute",
            )
        # Verify the action_outcomes table exists.
        with queue._conn:
            row = queue._conn.execute(
                "SELECT COUNT(*) AS n FROM action_outcomes "
                "LIMIT 1",
            ).fetchone()
        outcome_count = int(row["n"] or 0) if row else 0
        return StepResult(
            name="engine ranking",
            status="PASS" if outcome_count else "EMPTY",
            detail=(
                f"{outcome_count} outcome row(s) in queue; "
                "ranking analytics are ready"
            ),
        )
    except Exception as exc:  # noqa: BLE001
        return StepResult(
            name="engine ranking",
            status="FAIL",
            detail="raised during ranking probe",
            error=f"{type(exc).__name__}: {exc}",
        )


def _step_engine_alerts() -> StepResult:
    """Verify the engine-degradation detector works end-to-end."""
    try:
        from core.approval.outcome_trends import (
            compute_engine_alerts,
        )
        from core.approval.queue import get_approval_queue

        queue = get_approval_queue()
        alerts = compute_engine_alerts(
            queue,
            recent_hours=24.0,
            baseline_hours=168.0,
            threshold=0.2,
            min_recent=3,
        )
        return StepResult(
            name="engine alerts",
            status="PASS" if alerts else "EMPTY",
            detail=(
                f"{len(alerts)} engine(s) flagged; module wired"
            ),
        )
    except Exception as exc:  # noqa: BLE001
        return StepResult(
            name="engine alerts",
            status="FAIL",
            detail="raised during alerts probe",
            error=f"{type(exc).__name__}: {exc}",
        )


def _step_transfer_credit() -> StepResult:
    """Verify the credit-graph computation works end-to-end."""
    try:
        from core.approval.queue import get_approval_queue
        from core.transfer_credit import compute_transfer_credits

        queue = get_approval_queue()
        credits = compute_transfer_credits(queue, limit=10)
        return StepResult(
            name="transfer credit",
            status="PASS" if credits else "EMPTY",
            detail=(
                f"{len(credits)} credit row(s); attribution path "
                "wired"
            ),
        )
    except Exception as exc:  # noqa: BLE001
        return StepResult(
            name="transfer credit",
            status="FAIL",
            detail="raised during credit-graph probe",
            error=f"{type(exc).__name__}: {exc}",
        )


def _step_narrative_parsers() -> StepResult:
    """Verify ``core.transfer_narrative`` round-trips. Pure
    utility check -- catches any import-time / format-string
    regressions."""
    try:
        from core.transfer_narrative import (
            SQL_LIKE_CLAUSE,
            format_narrative,
            is_transfer_narrative,
            parse_engine_action,
            parse_source_run_count,
            parse_source_store,
            parse_target_store,
        )

        # Round-trip
        narrative = format_narrative(
            engine="loyalty", action_type="mint",
            from_store="alpha", to_store="beta",
            source_run_count=7,
        )
        checks = {
            "is_transfer_narrative": is_transfer_narrative(narrative),
            "parse_source_store": parse_source_store(narrative) == "alpha",
            "parse_target_store": parse_target_store(narrative) == "beta",
            "parse_engine_action": parse_engine_action(narrative) == (
                "loyalty", "mint",
            ),
            "parse_source_run_count": parse_source_run_count(
                narrative,
            ) == 7,
            "SQL_LIKE_CLAUSE": "narrative LIKE" in SQL_LIKE_CLAUSE,
        }
        failed = [k for k, v in checks.items() if not v]
        if failed:
            return StepResult(
                name="narrative parsers",
                status="FAIL",
                detail=f"failed round-trip on: {failed}",
            )
        return StepResult(
            name="narrative parsers",
            status="PASS",
            detail=f"{len(checks)} parser(s) round-trip cleanly",
        )
    except Exception as exc:  # noqa: BLE001
        return StepResult(
            name="narrative parsers",
            status="FAIL",
            detail="raised during parser probe",
            error=f"{type(exc).__name__}: {exc}",
        )


def _step_guardrail_roster() -> StepResult:
    """Verify the GUARDRAIL_ENGINES roster + guardrail_state
    helper. Validates the v2-guardrail surface."""
    try:
        from engines._agi_context import (
            GUARDRAIL_ENGINES,
            guardrail_state,
        )

        if not isinstance(GUARDRAIL_ENGINES, tuple):
            return StepResult(
                name="guardrail roster",
                status="FAIL",
                detail="GUARDRAIL_ENGINES is not a tuple",
            )
        state = guardrail_state()
        if set(state.keys()) != set(GUARDRAIL_ENGINES):
            return StepResult(
                name="guardrail roster",
                status="FAIL",
                detail=(
                    "guardrail_state keys don't match roster"
                ),
            )
        enabled = sum(1 for v in state.values() if v)
        return StepResult(
            name="guardrail roster",
            status="PASS",
            detail=(
                f"{len(GUARDRAIL_ENGINES)} engine(s) in roster; "
                f"{enabled} currently enabled via env var"
            ),
        )
    except Exception as exc:  # noqa: BLE001
        return StepResult(
            name="guardrail roster",
            status="FAIL",
            detail="raised during roster probe",
            error=f"{type(exc).__name__}: {exc}",
        )


def _step_daily_brief_dry() -> StepResult:
    """Verify the daily-brief sections all assemble without
    raising -- the cron path."""
    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "shopai_cli", "cli.py",
        )
        cli_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli_mod)

        # Call _cmd_daily_brief with a synthetic Namespace.
        import argparse as _argparse
        from io import StringIO
        from unittest.mock import patch

        ns = _argparse.Namespace(window_hours=24, json=True)
        buf = StringIO()
        try:
            with patch("sys.stdout", buf):
                cli_mod._cmd_daily_brief(ns)
        except SystemExit:
            pass
        envelope = buf.getvalue()
        if not envelope.strip():
            return StepResult(
                name="daily-brief",
                status="FAIL",
                detail="empty output",
            )
        # Parse to verify it's valid JSON
        data = json.loads(envelope)
        required_keys = {
            "window_hours", "stores", "totals", "alerts",
        }
        missing = required_keys - set(data.keys())
        if missing:
            return StepResult(
                name="daily-brief",
                status="FAIL",
                detail=f"envelope missing keys: {sorted(missing)}",
            )
        return StepResult(
            name="daily-brief",
            status="PASS",
            detail=(
                f"envelope has all expected sections; "
                f"{data['totals']['stores']} store(s), "
                f"{len(data['alerts'])} alert(s)"
            ),
        )
    except Exception as exc:  # noqa: BLE001
        return StepResult(
            name="daily-brief",
            status="FAIL",
            detail="raised during daily-brief probe",
            error=f"{type(exc).__name__}: {exc}",
        )


_STEPS = [
    ("Narrative parsers", _step_narrative_parsers),
    ("Guardrail roster", _step_guardrail_roster),
    ("World-model fleet", _step_world_model_fleet),
    ("Transfer-suggest pipeline", _step_transfer_suggest_pipeline),
    ("Engine ranking", _step_engine_ranking),
    ("Engine alerts", _step_engine_alerts),
    ("Transfer credit", _step_transfer_credit),
    ("Daily-brief", _step_daily_brief_dry),
]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Empire-AGI production smoke test. Walks the "
            "operator-visible surface read-only and reports "
            "pass / fail per step."
        ),
    )
    parser.add_argument(
        "--store", default="", dest="target_store",
        help=(
            "Optional: target store ID for transfer-suggest "
            "probe. Without it the probe just verifies the "
            "queue accepts store_id kwarg."
        ),
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit results as JSON.",
    )
    args = parser.parse_args()

    results: list[StepResult] = []
    for label, step in _STEPS:
        if step is _step_transfer_suggest_pipeline:
            result = step(args.target_store or None)
        else:
            try:
                result = step()
            except Exception as exc:  # noqa: BLE001
                result = StepResult(
                    name=label.lower(),
                    status="FAIL",
                    detail="unexpected outer raise",
                    error=(
                        # W962-67: don't embed the full
                        # traceback in the user-facing
                        # envelope (it carries the operator's
                        # Windows home path + module layout).
                        # Log full trace at DEBUG; envelope
                        # carries just type + first line of
                        # str(exc).
                        f"{type(exc).__name__}: {str(exc)[:120]}"
                    ),
                )
                logger.debug(
                    "empire_smoke %s raised: %s",
                    label, traceback.format_exc(),
                )
        results.append(result)

    pass_count = sum(1 for r in results if r.status == "PASS")
    empty_count = sum(1 for r in results if r.status == "EMPTY")
    fail_count = sum(1 for r in results if r.status == "FAIL")

    summary = {
        "total": len(results),
        "passed": pass_count,
        "empty": empty_count,
        "failed": fail_count,
        "all_green": fail_count == 0,
        "results": [asdict(r) for r in results],
    }

    if args.json:
        print(json.dumps(summary, indent=2, default=str))
    else:
        print("Empire-AGI smoke test")
        print()
        for r in results:
            badge = {
                "PASS": "[PASS] ",
                "EMPTY": "[EMPTY]",
                "FAIL": "[FAIL] ",
            }.get(r.status, "[????]")
            print(f"  {badge} {r.name:<30s} {r.detail}")
            if r.error:
                print(f"          error: {r.error.splitlines()[0]}")
        print()
        print(
            f"  Summary: {pass_count} pass  "
            f"{empty_count} empty  {fail_count} fail"
        )
        if fail_count == 0:
            print(
                "\n  All wiring green. Empire-AGI surface is "
                "ready to use."
            )
        else:
            print(
                "\n  At least one step failed. Fix wiring "
                "before relying on the empire-AGI surface."
            )

    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
