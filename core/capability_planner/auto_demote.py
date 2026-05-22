"""Capability-degradation -> operator-override bridge.

Closes the last manual step in the substrate's self-defense
layer. The pieces have been shipped over the last few PRs:

  1. ``plan_history.capability_degradations`` detects
     capabilities whose recent reliability dropped versus
     their baseline.
  2. ``capability_overrides.demote`` lets operators (or now,
     this bridge) declare "don't seed with this capability".
  3. ``Planner._apply_operator_overrides`` filters demoted
     capabilities OUT of the seed list before quarantine.

Without this bridge, step 1 surfaces the regression in
``daily-brief`` but does nothing about it -- an operator has
to notice + manually demote. This module is the env-gated
auto-action: when enabled, severely-degraded capabilities
self-demote so subsequent plans stop seeding them until the
operator clears the override.

Why env-gated (default OFF)
---------------------------
Auto-demoting a capability is a write to the operator's
override file. The same conservatism that gates
``alert_quarantine`` (PRs #292-#298) applies here:

  - Operators want to see WHAT WOULD be auto-demoted before
    delegating the decision. ``find_demote_candidates``
    always computes (read-only); only
    ``maybe_auto_demote_degraded`` flips the override file.
  - Severe threshold (0.4 default) is STRICTER than the
    operational "degradation" threshold (0.2). A capability
    has to be really broken before the bridge acts.

Env-var contract:

  - ``SHOPAI_AUTO_DEMOTE_DEGRADED=1`` -- enables the bridge.
    Default OFF.
  - ``SHOPAI_AUTO_DEMOTE_DROP_THRESHOLD`` -- minimum drop
    (baseline_rate - recent_rate) before auto-demote.
    Default ``0.4`` (40pp regression).
  - ``SHOPAI_AUTO_DEMOTE_MIN_RECENT_SAMPLE`` -- minimum recent
    sample size. Default ``3`` (cap must have actually been
    tried that many times in the recent window).
  - ``SHOPAI_AUTO_DEMOTE_RECENT_WINDOW_DAYS`` -- recent
    window. Default ``7``.
  - ``SHOPAI_AUTO_DEMOTE_BASELINE_WINDOW_DAYS`` -- baseline
    window. Default ``30``.

Pattern J: under pytest, ``maybe_auto_demote_degraded``
returns ``[]`` without writing. Tests exercising the bridge
patch ``_is_test_environment`` to ``False`` (the override
module already has its own Pattern J guard which is exercised
separately).
"""
from __future__ import annotations

import logging
import os
from typing import Any

from core.capability_planner import (
    capability_overrides,
    plan_history,
)

logger = logging.getLogger(__name__)


_ENV_ENABLED = "SHOPAI_AUTO_DEMOTE_DEGRADED"
_ENV_DROP = "SHOPAI_AUTO_DEMOTE_DROP_THRESHOLD"
_ENV_MIN_RECENT = "SHOPAI_AUTO_DEMOTE_MIN_RECENT_SAMPLE"
_ENV_RECENT_WINDOW = "SHOPAI_AUTO_DEMOTE_RECENT_WINDOW_DAYS"
_ENV_BASELINE_WINDOW = "SHOPAI_AUTO_DEMOTE_BASELINE_WINDOW_DAYS"
_ENV_RECOVERY = "SHOPAI_AUTO_DEMOTE_RECOVERY_THRESHOLD"

_DEFAULT_DROP = 0.4
_DEFAULT_MIN_RECENT = 3
_DEFAULT_RECENT_WINDOW_DAYS = 7
_DEFAULT_BASELINE_WINDOW_DAYS = 30
_DEFAULT_RECOVERY = 0.7

# Free-form reason logged on auto-demote so future override
# inspections distinguish bridge-driven demotes from operator-
# driven ones.
_AUTO_REASON_PREFIX = "auto_demote_degraded"


def is_enabled() -> bool:
    """Bridge is opt-in. Operator sets the env var when ready
    to delegate auto-demote to the substrate."""
    return os.environ.get(_ENV_ENABLED) == "1"


def drop_threshold() -> float:
    raw = os.environ.get(_ENV_DROP)
    if not raw:
        return _DEFAULT_DROP
    try:
        v = float(raw)
        if v <= 0:
            return _DEFAULT_DROP
        return v
    except (TypeError, ValueError) as exc:
        logger.debug(
            "invalid %s=%r; using default %s (%s)",
            _ENV_DROP, raw, _DEFAULT_DROP, exc,
        )
        return _DEFAULT_DROP


def min_recent_sample() -> int:
    raw = os.environ.get(_ENV_MIN_RECENT)
    if not raw:
        return _DEFAULT_MIN_RECENT
    try:
        return max(1, int(raw))
    except (TypeError, ValueError) as exc:
        logger.debug(
            "invalid %s=%r; using default %d (%s)",
            _ENV_MIN_RECENT, raw, _DEFAULT_MIN_RECENT, exc,
        )
        return _DEFAULT_MIN_RECENT


def recent_window_days() -> int:
    raw = os.environ.get(_ENV_RECENT_WINDOW)
    if not raw:
        return _DEFAULT_RECENT_WINDOW_DAYS
    try:
        return max(1, int(raw))
    except (TypeError, ValueError) as exc:
        logger.debug(
            "invalid %s=%r; using default %d (%s)",
            _ENV_RECENT_WINDOW, raw,
            _DEFAULT_RECENT_WINDOW_DAYS, exc,
        )
        return _DEFAULT_RECENT_WINDOW_DAYS


def recovery_threshold() -> float:
    """Minimum recent success rate for a bridge-demoted
    capability to be considered "recovered". Default 0.7."""
    raw = os.environ.get(_ENV_RECOVERY)
    if not raw:
        return _DEFAULT_RECOVERY
    try:
        v = float(raw)
        if v <= 0 or v > 1.0:
            return _DEFAULT_RECOVERY
        return v
    except (TypeError, ValueError) as exc:
        logger.debug(
            "invalid %s=%r; using default %s (%s)",
            _ENV_RECOVERY, raw, _DEFAULT_RECOVERY, exc,
        )
        return _DEFAULT_RECOVERY


def baseline_window_days() -> int:
    raw = os.environ.get(_ENV_BASELINE_WINDOW)
    if not raw:
        return _DEFAULT_BASELINE_WINDOW_DAYS
    try:
        return max(1, int(raw))
    except (TypeError, ValueError) as exc:
        logger.debug(
            "invalid %s=%r; using default %d (%s)",
            _ENV_BASELINE_WINDOW, raw,
            _DEFAULT_BASELINE_WINDOW_DAYS, exc,
        )
        return _DEFAULT_BASELINE_WINDOW_DAYS


def _is_test_environment() -> bool:
    """Pattern J -- bridge must never write under pytest. Tests
    that need to exercise the integration patch this."""
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def find_demote_candidates(
    *,
    drop: float | None = None,
    min_recent: int | None = None,
    recent_days: int | None = None,
    baseline_days: int | None = None,
) -> list[dict[str, Any]]:
    """Read-only preview: which capabilities WOULD auto-demote
    right now?

    Pulls ``plan_history.capability_degradations`` with the
    severity-tuned defaults (or caller overrides), then
    filters out capabilities that are already demoted by the
    operator -- only the NEW demotions are returned.

    Promoted capabilities are NOT excluded here: a promoted-
    then-degraded capability is exactly the case an operator
    most wants to see. The actual ``maybe_auto_demote_degraded``
    DOES skip promoted entries (replacing a promote with a
    demote silently would be hostile UX); the dry-run shows
    them with a ``blocked_by="promoted"`` marker so the
    operator can decide whether to clear the promote first.

    Args:
        drop: Min drop threshold. Default: env-tuned
            ``drop_threshold()``.
        min_recent: Min recent-window sample size. Default:
            env-tuned ``min_recent_sample()``.
        recent_days: Recent window in days. Default: env-tuned
            ``recent_window_days()``.
        baseline_days: Baseline window in days. Default:
            env-tuned ``baseline_window_days()``.

    Returns:
        Each row: ``{capability, baseline_rate, recent_rate,
        drop, recent_samples, baseline_samples, blocked_by}``.
        ``blocked_by`` is one of:
          - ``None`` -- not blocked; would auto-demote.
          - ``"already_demoted"`` -- operator (or prior auto-
            run) already demoted this capability.
          - ``"promoted"`` -- operator promoted it; the bridge
            won't overwrite a promote.
        Highest-drop first.
    """
    drop_th = drop if drop is not None else drop_threshold()
    min_rec = (
        min_recent if min_recent is not None
        else min_recent_sample()
    )
    rec_days = (
        recent_days if recent_days is not None
        else recent_window_days()
    )
    base_days = (
        baseline_days if baseline_days is not None
        else baseline_window_days()
    )
    regressions = plan_history.capability_degradations(
        recent_window_seconds=rec_days * 86400,
        baseline_window_seconds=base_days * 86400,
        min_recent_sample=min_rec,
        # Use baseline_sample = min_rec*2 floor so we don't
        # demote on a flimsy baseline; the default 5 baseline
        # samples is sufficient.
        min_baseline_sample=max(min_rec * 2, 5),
        drop_threshold=drop_th,
    )
    overrides = capability_overrides.load_overrides()
    demoted = overrides.demoted_names()
    promoted = overrides.promoted_names()

    out: list[dict[str, Any]] = []
    for r in regressions:
        cap = r["capability"]
        blocked: str | None = None
        if cap in demoted:
            blocked = "already_demoted"
        elif cap in promoted:
            blocked = "promoted"
        out.append({**r, "blocked_by": blocked})
    # capability_degradations already sorts by drop desc; we
    # preserve that order.
    return out


def maybe_auto_demote_degraded(
    *,
    drop: float | None = None,
    min_recent: int | None = None,
    recent_days: int | None = None,
    baseline_days: int | None = None,
) -> list[dict[str, Any]]:
    """Compute + apply auto-demotes in one call.

    Pattern J guard returns ``[]`` under pytest. Env-var
    ``SHOPAI_AUTO_DEMOTE_DEGRADED=1`` gate.

    Skips capabilities already on the demote list (idempotent)
    and capabilities the operator explicitly promoted (the
    promote takes precedence).

    Returns:
        List of ``{capability, drop, baseline_rate,
        recent_rate, reason}`` rows for capabilities actually
        demoted by this call. ``reason`` is the string stored
        on the override (auditing trail).
    """
    if _is_test_environment():
        return []
    if not is_enabled():
        return []
    candidates = find_demote_candidates(
        drop=drop,
        min_recent=min_recent,
        recent_days=recent_days,
        baseline_days=baseline_days,
    )
    if not candidates:
        return []

    applied: list[dict[str, Any]] = []
    for c in candidates:
        if c["blocked_by"] is not None:
            continue
        cap = c["capability"]
        reason = (
            f"{_AUTO_REASON_PREFIX}: "
            f"drop={c['drop']:.3f} "
            f"recent={c['recent_rate']:.3f}/{c['recent_samples']} "
            f"baseline={c['baseline_rate']:.3f}/"
            f"{c['baseline_samples']}"
        )
        ok = capability_overrides.demote(cap, reason=reason)
        if not ok:
            # Test-env guard or I/O error inside the override
            # writer; log and skip the row from the response.
            logger.debug(
                "auto_demote: demote(%s) returned False; "
                "skipping row", cap,
            )
            continue
        applied.append({
            "capability": cap,
            "drop": c["drop"],
            "baseline_rate": c["baseline_rate"],
            "recent_rate": c["recent_rate"],
            "recent_samples": c["recent_samples"],
            "baseline_samples": c["baseline_samples"],
            "reason": reason,
        })
    return applied


def config_summary() -> dict[str, Any]:
    """Return current bridge config -- used by daily-brief +
    world-model to surface state without re-resolving env vars
    at each call site."""
    return {
        "enabled": is_enabled(),
        "drop_threshold": drop_threshold(),
        "min_recent_sample": min_recent_sample(),
        "recent_window_days": recent_window_days(),
        "baseline_window_days": baseline_window_days(),
        "recovery_threshold": recovery_threshold(),
    }


def annotate_degradations(
    degradations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Annotate ``capability_degradations`` rows with their
    bridge status so operator surfaces can render severity.

    For each input row, adds a ``bridge_status`` field:

      - ``"auto_demoted"`` -- already in the override list
        (the bridge has already acted; subsequent plans
        already skip this capability).
      - ``"would_demote"`` -- drop crosses the bridge
        threshold and is unblocked. Next cycle the bridge
        WILL demote it (when env-gated on).
      - ``"watching"`` -- drop crosses the degradation
        threshold but not the severe threshold. The bridge
        won't act yet; operator sees this as an early-
        warning signal.

    Input rows are not mutated; new rows with the extra
    field are returned in input order.

    Lookups are cached across rows so the function is
    O(degradations) not O(degradations * overrides).
    """
    if not degradations:
        return []
    overrides = capability_overrides.load_overrides()
    demoted = overrides.demoted_names()
    promoted = overrides.promoted_names()
    threshold = drop_threshold()

    out: list[dict[str, Any]] = []
    for r in degradations:
        cap = r.get("capability", "")
        drop = float(r.get("drop", 0.0) or 0.0)
        if cap in demoted:
            status = "auto_demoted"
        elif drop >= threshold and cap not in promoted:
            status = "would_demote"
        else:
            status = "watching"
        out.append({**r, "bridge_status": status})
    return out


def find_watchlist(
    *,
    recent_days: int | None = None,
    baseline_days: int | None = None,
    min_recent: int | None = None,
) -> list[dict[str, Any]]:
    """Read-only: capabilities approaching the bridge
    threshold but not yet at it.

    Calls ``capability_degradations`` with the default
    operational drop threshold (0.2 -- the degradation
    flag), then annotates each row and filters to just the
    ``watching`` tier. The result is the operator's early-
    warning surface: "these capabilities are regressing
    but the bridge isn't acting yet -- investigate before
    they cross severity."

    Args:
        recent_days: Recent window in days. Default:
            env-tuned ``recent_window_days()``.
        baseline_days: Baseline window in days. Default:
            env-tuned ``baseline_window_days()``.
        min_recent: Min recent sample size. Default:
            env-tuned ``min_recent_sample()``.

    Returns:
        Each row carries the same fields as
        ``capability_degradations`` plus
        ``bridge_status="watching"``. Sorted highest-drop
        first (same as upstream).
    """
    rec_days = (
        recent_days if recent_days is not None
        else recent_window_days()
    )
    base_days = (
        baseline_days if baseline_days is not None
        else baseline_window_days()
    )
    min_rec = (
        min_recent if min_recent is not None
        else min_recent_sample()
    )

    # Use the operational degradation threshold (0.2) not
    # the bridge's severe threshold -- we want the wider
    # set so we can extract the "below severe but above
    # operational" subset.
    degs = plan_history.capability_degradations(
        recent_window_seconds=rec_days * 86400,
        baseline_window_seconds=base_days * 86400,
        min_recent_sample=min_rec,
        min_baseline_sample=max(min_rec * 2, 5),
        drop_threshold=0.2,
    )
    annotated = annotate_degradations(degs)
    return [
        r for r in annotated
        if r.get("bridge_status") == "watching"
    ]


def find_release_candidates(
    *,
    recovery: float | None = None,
    min_recent: int | None = None,
    recent_days: int | None = None,
) -> list[dict[str, Any]]:
    """Read-only: bridge-demoted capabilities whose recent
    reliability has recovered enough to clear the demote.

    Sister to ``find_demote_candidates`` -- the demote side
    detects regressions; this one detects recoveries. The
    bridge demoted capabilities silently in the
    ``maybe_auto_demote_degraded`` call; without a recovery
    helper, those demotes stay forever even after the
    underlying issue is fixed.

    Only ``auto_demote_degraded``-prefixed demotes are
    considered. Operator-driven demotes (manual ``shopai
    capabilities demote``) are left alone because the
    operator's reason may persist even if reliability has
    recovered.

    Args:
        recovery: Minimum recent success rate to qualify.
            Default: env-tuned ``recovery_threshold()``
            (0.7).
        min_recent: Minimum recent-window sample size for
            the candidate to be considered. Default: env-
            tuned ``min_recent_sample()``.
        recent_days: Recent window in days. Default: env-
            tuned ``recent_window_days()``.

    Returns:
        Highest-recovery first. Each row:
          {capability, recent_rate, recent_samples,
           demote_reason, demoted_at}
        Empty when no bridge demotes exist or no demoted
        capability has recovered.
    """
    rec_th = recovery if recovery is not None else recovery_threshold()
    min_rec = (
        min_recent if min_recent is not None
        else min_recent_sample()
    )
    rec_days = (
        recent_days if recent_days is not None
        else recent_window_days()
    )

    overrides = capability_overrides.load_overrides()
    # Filter to bridge-driven demotes only.
    auto_demoted = [
        e for e in overrides.entries
        if e.kind == "demote"
        and e.reason.startswith("auto_demote_degraded")
    ]
    if not auto_demoted:
        return []

    leaderboard = plan_history.capability_leaderboard(
        since_seconds=rec_days * 86400,
        min_sample_size=min_rec,
        top_n=1000,
    )
    rates_by_cap: dict[str, dict[str, Any]] = {
        r["capability"]: r for r in leaderboard
    }

    out: list[dict[str, Any]] = []
    for entry in auto_demoted:
        row = rates_by_cap.get(entry.name)
        if row is None:
            # No recent samples -- can't confirm recovery,
            # skip. Operator can clear manually if they
            # want to retry.
            continue
        if row["success_rate"] < rec_th:
            continue
        out.append({
            "capability": entry.name,
            "recent_rate": row["success_rate"],
            "recent_samples": row["executed_count"],
            "demote_reason": entry.reason,
            "demoted_at": entry.recorded_at,
        })
    out.sort(key=lambda r: -r["recent_rate"])
    return out


def maybe_release_recovered(
    *,
    recovery: float | None = None,
    min_recent: int | None = None,
    recent_days: int | None = None,
) -> list[dict[str, Any]]:
    """Compute + apply release of recovered bridge-demoted
    capabilities.

    Pattern J short-circuit returns ``[]`` under pytest.
    Unlike ``maybe_auto_demote_degraded`` this function is
    NOT env-gated -- the bridge's demote requires explicit
    opt-in (because flipping a previously-OK capability is
    a write that affects future plans), but RELEASING is the
    safe direction. An operator who finds the bridge has
    quarantined too aggressively can always re-add a manual
    demote.

    Returns the list of rows actually released (same shape
    as ``find_release_candidates``).
    """
    if _is_test_environment():
        return []
    candidates = find_release_candidates(
        recovery=recovery,
        min_recent=min_recent,
        recent_days=recent_days,
    )
    if not candidates:
        return []
    released: list[dict[str, Any]] = []
    for c in candidates:
        ok = capability_overrides.clear(c["capability"])
        if not ok:
            logger.debug(
                "auto_demote: clear(%s) returned False; "
                "skipping row", c["capability"],
            )
            continue
        released.append(c)
    return released
