"""Data Quality Engine — memory triage and scoring.

Wave 2 #3 in-place improvement. The existing
:class:`UnifiedMemory` stores everything it's handed. That was
fine when the surface area was narrow, but once the system
starts producing error logs, A/B signals, half-baked reflections,
and real knowledge snippets the "one-bucket" design starts to
choke — every reader has to wade through noise, and every
writer has to guess what "importance" means.

This module fixes the gap without touching :class:`UnifiedMemory`
itself. It's pure functions over a small :class:`MemoryRecord`
dataclass, so any caller can classify / score / decay a record
in isolation. Wave 2 #4 will wire the classifier into the
memory facade so writes get routed to the right satellite
layer; Wave 2 #6 (SLA tracker) will reuse the scoring
function for per-subsystem quality metrics.

Key concepts
------------

**MemoryClass** — four buckets:
    * ``KNOWLEDGE`` — durable facts, rules, learned lessons
    * ``ERROR``     — failure events with enough detail to learn from
    * ``SIGNAL``    — short-lived observations (metrics, A/B results,
                      rate-limit hits)
    * ``NOISE``     — low-signal noise (debug spam, redundant logs)

**Quality score** — weighted sum over five dimensions:

    0.30 * quality
  + 0.25 * confidence
  + 0.20 * recency
  + 0.15 * success_rate
  + 0.10 * usage

  Each dimension is normalised to ``[0, 1]`` before weighting.
  The weights are fixed (not configurable) so every subsystem
  gets the same ordering and the scoring is cross-comparable.

**Temporal decay** — exponential half-life per class:

    KNOWLEDGE: 30 days
    ERROR:     14 days
    SIGNAL:     7 days
    NOISE:      1 day

  Decay is applied to the *recency* dimension only — the other
  dimensions capture the record's intrinsic value and should
  not rot.

Design notes
------------

* **Pure functions** — no I/O, no globals, no threading. The
  classifier is a static decision tree over the record's shape;
  the scorer is arithmetic. Testability is trivial and the
  engine can be called from any thread.
* **Stable ordering** — ``score(a) > score(b)`` must be
  transitively consistent across invocations, so ties are
  broken by ``created_at`` ascending (older wins). This keeps
  sort order deterministic when two records have identical
  scores.
* **No ML** — classification is rule-based. ShopAI's memory
  intelligence is explainable by design; operators need to
  trace *why* a record was classified, not stare at a model's
  softmax output.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class MemoryClass(str, Enum):
    """Quality-derived class of a memory record."""

    KNOWLEDGE = "knowledge"
    ERROR     = "error"
    SIGNAL    = "signal"
    NOISE     = "noise"


# Half-lives in seconds per class — controls how fast the
# *recency* dimension decays. Tweaking these changes how long
# a record "stays fresh" in the scoring function.
_HALF_LIFE_SECONDS: dict[MemoryClass, float] = {
    MemoryClass.KNOWLEDGE: 30 * 86_400.0,
    MemoryClass.ERROR:     14 * 86_400.0,
    MemoryClass.SIGNAL:     7 * 86_400.0,
    MemoryClass.NOISE:      1 * 86_400.0,
}


# Score weights. Must sum to 1.0 so the final score is in [0,1].
_SCORE_WEIGHTS: dict[str, float] = {
    "quality":      0.30,
    "confidence":   0.25,
    "recency":      0.20,
    "success_rate": 0.15,
    "usage":        0.10,
}
assert abs(sum(_SCORE_WEIGHTS.values()) - 1.0) < 1e-9, (
    "_SCORE_WEIGHTS must sum to 1.0"
)


# ---------------------------------------------------------------------------
# Record dataclass
# ---------------------------------------------------------------------------


@dataclass
class MemoryRecord:
    """Canonical shape the quality engine operates on.

    Callers construct these from their own memory payloads — the
    engine does not mandate persistence format. Only the fields
    used by :func:`classify` and :func:`score` are read; the rest
    of the record (body, tags, etc.) can be stored alongside in
    :attr:`payload` for retrieval.

    Fields
    ------
    kind:
        Short string hint from the producer (e.g. ``"rule"``,
        ``"error"``, ``"metric"``, ``"debug"``). The classifier
        uses this as the primary signal; other fields act as
        tiebreakers.
    quality:
        Producer-asserted quality in ``[0, 1]``. Defaults to 0.5
        when the producer can't commit to a number.
    confidence:
        Producer-asserted confidence in ``[0, 1]``. Defaults to
        0.5.
    success_rate:
        For records that track an action outcome, the rolling
        success rate in ``[0, 1]``. Defaults to 0.5 when the
        record isn't outcome-linked.
    usage:
        Number of times this record has been consulted /
        retrieved. Used to reward records that actually get
        referenced by downstream subsystems.
    created_at:
        Unix timestamp (seconds). Defaults to "now".
    tags:
        Free-form tag list used as a secondary classifier
        signal (e.g. ``"error"`` / ``"noise"`` tags).
    payload:
        Arbitrary user data kept with the record for retrieval.
    """

    kind:         str
    quality:      float                 = 0.5
    confidence:   float                 = 0.5
    success_rate: float                 = 0.5
    usage:        int                   = 0
    created_at:   float                 = field(default_factory=time.time)
    tags:         tuple[str, ...]       = ()
    payload:      dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


_ERROR_KINDS = frozenset({
    "error", "exception", "failure", "fail", "traceback", "crash",
    "timeout", "rate_limit",
})

_SIGNAL_KINDS = frozenset({
    "metric", "metrics", "signal", "observation", "ab_result",
    "ab_test", "telemetry", "probe", "heartbeat",
})

_KNOWLEDGE_KINDS = frozenset({
    "rule", "lesson", "fact", "knowledge", "decision", "outcome",
    "policy", "principle", "reflection",
})

_NOISE_KINDS = frozenset({
    "debug", "trace", "spam", "noise", "verbose",
})


def classify(record: MemoryRecord) -> MemoryClass:
    """Classify a record into :class:`MemoryClass`.

    Decision order (first match wins):

    1. Explicit ``"noise"`` tag → ``NOISE``
    2. Explicit ``"error"`` tag or kind in ``_ERROR_KINDS`` → ``ERROR``
    3. Kind in ``_KNOWLEDGE_KINDS`` OR quality >= 0.75 AND
       confidence >= 0.75 → ``KNOWLEDGE``
    4. Kind in ``_SIGNAL_KINDS`` → ``SIGNAL``
    5. Kind in ``_NOISE_KINDS`` → ``NOISE``
    6. Anything with quality < 0.25 OR confidence < 0.25 → ``NOISE``
    7. Fallback → ``SIGNAL`` (short-lived, decays fast)
    """
    kind = (record.kind or "").lower().strip()
    tags = {t.lower() for t in (record.tags or ())}

    if "noise" in tags:
        return MemoryClass.NOISE
    if "error" in tags or kind in _ERROR_KINDS:
        return MemoryClass.ERROR
    if kind in _KNOWLEDGE_KINDS:
        return MemoryClass.KNOWLEDGE
    if record.quality >= 0.75 and record.confidence >= 0.75:
        return MemoryClass.KNOWLEDGE
    if kind in _SIGNAL_KINDS:
        return MemoryClass.SIGNAL
    if kind in _NOISE_KINDS:
        return MemoryClass.NOISE
    if record.quality < 0.25 or record.confidence < 0.25:
        return MemoryClass.NOISE
    return MemoryClass.SIGNAL


# ---------------------------------------------------------------------------
# Decay + scoring
# ---------------------------------------------------------------------------


def decay_recency(
    created_at: float,
    memory_class: MemoryClass,
    now: float | None = None,
) -> float:
    """Exponential-decay recency score in ``[0, 1]``.

    Uses an exponential with half-life from ``_HALF_LIFE_SECONDS``:

        recency = 0.5 ** (age / half_life)

    A fresh record (age == 0) scores 1.0; after one half-life it
    scores 0.5; after two, 0.25; and so on.
    """
    now = time.time() if now is None else now
    age = max(0.0, now - created_at)
    half_life = _HALF_LIFE_SECONDS[memory_class]
    if half_life <= 0:
        return 0.0
    return 0.5 ** (age / half_life)


def _usage_score(usage: int) -> float:
    """Map integer usage counter to a ``[0, 1]`` score.

    Diminishing-returns curve ``1 - 1 / (1 + usage/10)`` so the
    first few reads matter more than the next thousand. Prevents
    heavily-polled records from saturating the score without
    punishing genuinely popular ones.
    """
    if usage <= 0:
        return 0.0
    return 1.0 - 1.0 / (1.0 + usage / 10.0)


def _clamp01(x: float) -> float:
    if math.isnan(x):
        return 0.0
    return max(0.0, min(1.0, float(x)))


def score(
    record: MemoryRecord,
    *,
    memory_class: MemoryClass | None = None,
    now: float | None = None,
) -> float:
    """Compute the weighted quality score in ``[0, 1]``.

    Break down each dimension:

    * ``quality``      → record.quality (clamped)
    * ``confidence``   → record.confidence (clamped)
    * ``recency``      → :func:`decay_recency`
    * ``success_rate`` → record.success_rate (clamped)
    * ``usage``        → :func:`_usage_score`

    ``memory_class`` defaults to :func:`classify` if not supplied,
    so callers can chain the two without repeating work when they
    already know the class.
    """
    cls = memory_class or classify(record)
    q = _clamp01(record.quality)
    c = _clamp01(record.confidence)
    r = decay_recency(record.created_at, cls, now=now)
    s = _clamp01(record.success_rate)
    u = _usage_score(record.usage)
    return (
        _SCORE_WEIGHTS["quality"]      * q
        + _SCORE_WEIGHTS["confidence"]   * c
        + _SCORE_WEIGHTS["recency"]      * r
        + _SCORE_WEIGHTS["success_rate"] * s
        + _SCORE_WEIGHTS["usage"]        * u
    )


def rank(
    records: Iterable[MemoryRecord],
    *,
    now: float | None = None,
) -> list[tuple[MemoryRecord, float, MemoryClass]]:
    """Classify + score + sort a batch of records.

    Returns a list of ``(record, score, memory_class)`` tuples
    sorted by score descending. Ties are broken by ``created_at``
    ascending (older wins) for deterministic ordering.
    """
    enriched = [
        (r, score(r, memory_class=classify(r), now=now), classify(r))
        for r in records
    ]
    enriched.sort(key=lambda t: (-t[1], t[0].created_at))
    return enriched


def is_worth_keeping(
    record: MemoryRecord,
    *,
    threshold: float = 0.25,
    now: float | None = None,
) -> bool:
    """Return ``True`` if the record's score is above *threshold*.

    NOISE records are always below threshold unless they carry
    unusually high quality/confidence — a useful hook for memory
    GC passes that want to prune without iterating classes by
    hand.
    """
    return score(record, now=now) >= threshold


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


def describe(
    record: MemoryRecord,
    *,
    now: float | None = None,
) -> dict[str, Any]:
    """Return a debug-friendly breakdown of the score components.

    Useful for audit logs and "why was this record scored X"
    questions from operators.
    """
    cls = classify(record)
    q = _clamp01(record.quality)
    c = _clamp01(record.confidence)
    r = decay_recency(record.created_at, cls, now=now)
    s = _clamp01(record.success_rate)
    u = _usage_score(record.usage)
    return {
        "class":       cls.value,
        "components":  {
            "quality":      q,
            "confidence":   c,
            "recency":      r,
            "success_rate": s,
            "usage":        u,
        },
        "weights":     dict(_SCORE_WEIGHTS),
        "score":       (
            _SCORE_WEIGHTS["quality"]      * q
            + _SCORE_WEIGHTS["confidence"]   * c
            + _SCORE_WEIGHTS["recency"]      * r
            + _SCORE_WEIGHTS["success_rate"] * s
            + _SCORE_WEIGHTS["usage"]        * u
        ),
        "half_life_s": _HALF_LIFE_SECONDS[cls],
    }


__all__ = [
    "MemoryClass",
    "MemoryRecord",
    "classify",
    "decay_recency",
    "score",
    "rank",
    "is_worth_keeping",
    "describe",
]
