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

_DEFAULT_DROP = 0.4
_DEFAULT_MIN_RECENT = 3
_DEFAULT_RECENT_WINDOW_DAYS = 7
_DEFAULT_BASELINE_WINDOW_DAYS = 30

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
    }
