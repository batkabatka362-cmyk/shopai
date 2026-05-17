"""Outcome-list rollup utility — shared polarity + revenue counter.

Each ``action_outcomes`` row carries ``polarity`` (positive /
negative / neutral) and an optional ``metrics`` dict that may
contain ``revenue``. Five CLI handlers + the world-model
snapshot section all roll up these rows the same way:

  - Count rows per polarity
  - Sum ``metrics.revenue`` across rows (skip malformed values)
  - Compute ``outcome_score = positive / (positive + negative);
    None when no polarised events`` for rankings

Pre-this-module, the rollup loop lived inline in:

- ``shopai transfer outcomes``
- ``shopai engine fleet``
- ``shopai engine compare``
- ``shopai engine ranking``
- ``shopai daily-brief`` transfer section

This module centralises the math. Callers that adopt
``aggregate_outcomes(...)`` get a tidy ``OutcomeStats`` dataclass
back; format changes (adding new polarity values, computing
percentiles, etc.) land in one place instead of five.

Migration is incremental — adding the new module here is
non-breaking; CLI handlers can migrate in follow-up PRs without
behaviour change.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class OutcomeStats:
    """Rolled-up stats over a list of action_outcomes rows.

    Fields:
        total: Total outcome rows aggregated.
        positive: Rows with ``polarity == "positive"``.
        negative: Rows with ``polarity == "negative"``.
        neutral: Rows with ``polarity == "neutral"``.
        other: Rows whose polarity didn't match any of the
            recognised values (None, missing key, unrecognised
            string). Tracked so callers can detect schema drift.
        revenue: Sum of ``metrics.revenue`` across all rows, with
            malformed values silently skipped. Always a float.
        outcome_score: ``positive / (positive + negative)``,
            or ``None`` when there were no polarised events.
            Mirrors the ranking rule used in engine-ranking /
            engine-fleet / engine-compare.
    """

    total: int = 0
    positive: int = 0
    negative: int = 0
    neutral: int = 0
    other: int = 0
    revenue: float = 0.0
    outcome_score: float | None = None

    def as_dict(self) -> dict[str, Any]:
        """JSON-safe representation for envelopes.

        ``outcome_score`` may be ``None`` — JSON callers should
        accept that; CSV/text callers should format as "n/a".
        """
        return asdict(self)


def aggregate_outcomes(
    outcomes: Iterable[dict[str, Any]] | None,
) -> OutcomeStats:
    """Roll a list of outcome dicts into one :class:`OutcomeStats`.

    Args:
        outcomes: Iterable of outcome dicts as returned by
            ``ApprovalQueue.get_outcomes(action_id)``. Each dict
            is expected to carry ``polarity`` (str) and an
            optional ``metrics`` dict containing ``revenue``.
            ``None`` is treated as an empty iterable.

    Returns:
        :class:`OutcomeStats` with counters + revenue + score.

    Robust to:
        - Empty / None input (returns zeroed stats).
        - Non-dict entries (counted as ``other``, no crash).
        - Missing ``polarity`` key (``other``).
        - Unrecognised polarity values (``other``).
        - Missing ``metrics`` or non-dict ``metrics``
          (revenue stays at zero for that row).
        - Non-numeric / None ``revenue`` (skipped silently).
    """
    total = 0
    positive = negative = neutral = other = 0
    revenue = 0.0

    for entry in outcomes or []:
        total += 1
        if not isinstance(entry, dict):
            other += 1
            continue
        pol = entry.get("polarity")
        if pol == "positive":
            positive += 1
        elif pol == "negative":
            negative += 1
        elif pol == "neutral":
            neutral += 1
        else:
            other += 1
        metrics = entry.get("metrics")
        if isinstance(metrics, dict):
            raw = metrics.get("revenue", 0)
            try:
                revenue += float(raw or 0)
            except (TypeError, ValueError):
                pass

    if (positive + negative) > 0:
        score: float | None = positive / (positive + negative)
    else:
        score = None

    return OutcomeStats(
        total=total,
        positive=positive,
        negative=negative,
        neutral=neutral,
        other=other,
        revenue=revenue,
        outcome_score=score,
    )
