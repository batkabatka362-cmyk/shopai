"""Auto-promote bridge — the symmetric counterpart to
``auto_demote``.

The auto-demote bridge protects against rotten capabilities
by pulling regression candidates out of the planner's seed
list. The MISSING half: rewarding proven winners. Without
this, the substrate ages by SHRINKING but never GROWING.

This module does the opposite: when a capability has a
high success rate over enough samples, auto-promote it via
the operator overrides. The planner's
``_apply_operator_overrides`` already boosts promoted caps
into the seed list -- this layer just feeds the right
candidates in autonomously.

Conservative on purpose:
  - HIGH success rate threshold (0.95) -- the bar for
    "proven winner" is much stricter than the 0.5 floor
    auto-demote uses.
  - Requires enough samples (5) so a single-event lucky
    cap doesn't get promoted.
  - Won't override operator demotes -- if the operator
    flagged a cap, this layer respects that.
  - Won't promote auto-demoted entries (catches the post-
    release thrashing case).

Env-var contract (default OFF for safety):

  - ``SHOPAI_AUTO_PROMOTE_RELIABLE=1`` -- enables the
    bridge.
  - ``SHOPAI_AUTO_PROMOTE_THRESHOLD`` -- min success rate.
    Default 0.95.
  - ``SHOPAI_AUTO_PROMOTE_MIN_SAMPLE`` -- min executed
    appearance count. Default 5.
  - ``SHOPAI_AUTO_PROMOTE_WINDOW_DAYS`` -- look-back
    window. Default 30.

Pattern J: ``maybe_auto_promote_reliable`` short-circuits
under pytest. ``find_promote_candidates`` always computes.
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


_ENV_ENABLED = "SHOPAI_AUTO_PROMOTE_RELIABLE"
_ENV_THRESHOLD = "SHOPAI_AUTO_PROMOTE_THRESHOLD"
_ENV_MIN_SAMPLE = "SHOPAI_AUTO_PROMOTE_MIN_SAMPLE"
_ENV_WINDOW = "SHOPAI_AUTO_PROMOTE_WINDOW_DAYS"

_DEFAULT_THRESHOLD = 0.95
_DEFAULT_MIN_SAMPLE = 5
_DEFAULT_WINDOW_DAYS = 30

_AUTO_REASON_PREFIX = "auto_promote_reliable"


def is_enabled() -> bool:
    return os.environ.get(_ENV_ENABLED) == "1"


def threshold() -> float:
    raw = os.environ.get(_ENV_THRESHOLD)
    if not raw:
        return _DEFAULT_THRESHOLD
    try:
        v = float(raw)
        if v <= 0 or v > 1.0:
            return _DEFAULT_THRESHOLD
        return v
    except (TypeError, ValueError):
        return _DEFAULT_THRESHOLD


def min_sample() -> int:
    raw = os.environ.get(_ENV_MIN_SAMPLE)
    if not raw:
        return _DEFAULT_MIN_SAMPLE
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return _DEFAULT_MIN_SAMPLE


def window_days() -> int:
    raw = os.environ.get(_ENV_WINDOW)
    if not raw:
        return _DEFAULT_WINDOW_DAYS
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return _DEFAULT_WINDOW_DAYS


def _is_test_environment() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def find_promote_candidates(
    *,
    threshold_override: float | None = None,
    min_sample_override: int | None = None,
    window_days_override: int | None = None,
) -> list[dict[str, Any]]:
    """Read-only: which capabilities WOULD auto-promote
    right now?

    Walks the capability leaderboard, filters to entries
    above the success-rate + sample-size thresholds,
    excludes anything already promoted/demoted by the
    operator (or by this bridge in a prior run).

    Returns:
        Each row: ``{capability, success_rate,
        executed_count, success_count, blocked_by}``.
        ``blocked_by`` is one of:
          - ``None`` -- not blocked; would auto-promote.
          - ``"already_promoted"`` -- in the override list.
          - ``"demoted"`` -- demoted (manual OR auto). The
            demote signal takes precedence; never undo a
            demote via auto-promote.
        Highest-success-rate first.
    """
    thresh = (
        threshold_override
        if threshold_override is not None
        else threshold()
    )
    min_s = (
        min_sample_override
        if min_sample_override is not None
        else min_sample()
    )
    win_d = (
        window_days_override
        if window_days_override is not None
        else window_days()
    )

    try:
        rows = plan_history.capability_leaderboard(
            since_seconds=win_d * 86400,
            min_sample_size=min_s,
            top_n=200,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "find_promote_candidates: lookup raised: %s",
            exc,
        )
        return []
    if not rows:
        return []

    try:
        overrides = capability_overrides.load_overrides()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "find_promote_candidates: overrides "
            "raised: %s", exc,
        )
        overrides = capability_overrides.CapabilityOverrides(
            entries=[],
        )
    demoted = overrides.demoted_names()
    promoted = overrides.promoted_names()

    out: list[dict[str, Any]] = []
    for r in rows:
        rate = float(r.get("success_rate", 0.0) or 0.0)
        if rate < thresh:
            continue
        cap = r["capability"]
        blocked: str | None = None
        if cap in demoted:
            blocked = "demoted"
        elif cap in promoted:
            blocked = "already_promoted"
        out.append({**r, "blocked_by": blocked})
    out.sort(key=lambda r: -r["success_rate"])
    return out


def maybe_auto_promote_reliable(
    *,
    threshold_override: float | None = None,
    min_sample_override: int | None = None,
    window_days_override: int | None = None,
) -> list[dict[str, Any]]:
    """Compute + apply auto-promotes in one call.

    Pattern J guard short-circuits under pytest. Env gate
    ``SHOPAI_AUTO_PROMOTE_RELIABLE=1`` required for the
    write.

    Returns list of ``{capability, success_rate,
    executed_count, reason}`` for caps actually promoted by
    this call.
    """
    if _is_test_environment():
        return []
    if not is_enabled():
        return []
    candidates = find_promote_candidates(
        threshold_override=threshold_override,
        min_sample_override=min_sample_override,
        window_days_override=window_days_override,
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
            f"rate={c['success_rate']:.3f} "
            f"n={c['executed_count']}"
        )
        ok = capability_overrides.promote(
            cap, reason=reason,
        )
        if not ok:
            logger.debug(
                "auto_promote: promote(%s) returned "
                "False; skipping row", cap,
            )
            continue
        applied.append({
            "capability": cap,
            "success_rate": c["success_rate"],
            "executed_count": c["executed_count"],
            "success_count": c["success_count"],
            "reason": reason,
        })
    return applied


def config_summary() -> dict[str, Any]:
    return {
        "enabled": is_enabled(),
        "threshold": threshold(),
        "min_sample": min_sample(),
        "window_days": window_days(),
    }
