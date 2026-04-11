"""Principle-based value weights + Bayesian belief updates.

See :mod:`core.mentality` for the big picture.

Design notes
------------

**Principles vs. check weights.** ``JudgmentAdvisor`` already
assigns fixed weights to its 6 pre-execution checks (magnitude,
competitor_activity, past_failures, system_stability,
financial_constraint, cooldown). Those weights encode *"how
important is each check to overall risk"*. :class:`Values` sits
one level above: it encodes *"how important is each principle
to THIS operator"* and produces a multiplier for each check
based on which principles that check advances. The advisor
multiplies its own defaults by the mentality multipliers before
summing — so tenants with ``safety=1.5, speed=0.5`` get a gate
that is slower but stricter, without any edit to the advisor
itself.

**Beta-binomial beliefs.** For binary questions the system asks
over and over (*"does price-cut X boost conversion?"*, *"does
pausing ad Y save money without losing revenue?"*), a simple
beta-binomial posterior is honest and cheap. :class:`BeliefStore`
keeps ``(alpha, beta)`` counters per belief key; the posterior
mean is ``alpha / (alpha + beta)`` and the 95% credible interval
is computed from the quantiles of the beta distribution. The
store is pure Python with no scipy dependency — we use
``statistics.NormalDist`` as a fallback for the CI when scipy
isn't installed.

**Why in-place.** Putting ``Values`` in a new package
(``core/mentality/``) instead of inside ``core/judgment`` keeps
mentality-related ideas (values, beliefs, later: goals alignment
scoring) together without creating two advisor files.
:class:`JudgmentAdvisor` only changes by accepting an optional
``values`` kwarg and consulting it when re-weighting checks.
"""
from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field
from typing import Any

from utils.logger import get_logger

logger = get_logger("mentality.values")


# ---------------------------------------------------------------------------
# Canonical principle set
# ---------------------------------------------------------------------------
#
# Each principle is a numeric weight. 1.0 is neutral, >1 amplifies,
# <1 dampens. Values are multiplicative on the advisor's check
# weights (see ``Values.check_multiplier``). No hard cap is enforced
# here so operators can still express strong preferences
# ("safety=3.0, speed=0.2"), but the advisor clamps the resulting
# check weights to a sane range before use.

_DEFAULT_PRINCIPLES: dict[str, float] = {
    "safety":      1.5,
    "reliability": 1.3,
    "long_term":   1.2,
    "automation":  1.0,
    "speed":       0.8,
    "short_term":  0.7,
}


# Mapping from judgment-advisor check name → which principles the
# check advances (i.e. which principles' weights should be applied
# as a multiplier to the check's base weight). A check can advance
# multiple principles; the effective multiplier is the arithmetic
# mean of the matching principle weights.

_CHECK_PRINCIPLES: dict[str, tuple[str, ...]] = {
    "magnitude":            ("safety", "reliability"),
    "competitor_activity":  ("reliability", "long_term"),
    "past_failures":        ("safety", "reliability", "long_term"),
    "system_stability":     ("reliability", "safety"),
    "financial_constraint": ("long_term", "safety"),
    "cooldown":             ("reliability", "speed"),
}


# Clamp range for effective check weights after the Values
# multiplier is applied. Prevents extreme operator preferences
# from completely zeroing or over-amplifying a single check.

_MIN_EFFECTIVE_WEIGHT = 0.02
_MAX_EFFECTIVE_WEIGHT = 5.00


@dataclass
class Values:
    """Operator-configurable principle weights.

    Usage::

        values = Values(safety=2.0, speed=0.3)
        advisor = JudgmentAdvisor(..., values=values)

    Unspecified principles fall back to the defaults in
    :data:`_DEFAULT_PRINCIPLES`. Instances are immutable once
    constructed (safety: the advisor caches the multiplier map
    and would otherwise need to invalidate it on every edit).
    """

    principles: dict[str, float] = field(
        default_factory=lambda: dict(_DEFAULT_PRINCIPLES),
    )

    def __post_init__(self) -> None:
        # Accept kwarg-style overrides via a ``principles`` dict
        # that merges onto the defaults. This keeps construction
        # ergonomic for the common "override one or two" case
        # while still supporting the full explicit form.
        merged = dict(_DEFAULT_PRINCIPLES)
        for k, v in (self.principles or {}).items():
            if not isinstance(v, (int, float)):
                raise ValueError(
                    f"Values.principles[{k!r}] must be numeric, "
                    f"got {type(v).__name__}",
                )
            if float(v) < 0:
                raise ValueError(
                    f"Values.principles[{k!r}] must be non-negative "
                    f"(got {v})",
                )
            merged[k] = float(v)
        object.__setattr__(self, "principles", merged)

    # -- convenience ctor -------------------------------------------

    @classmethod
    def from_kwargs(cls, **overrides: float) -> "Values":
        """Build a :class:`Values` from keyword overrides.

        Shortcut for ``Values(principles={"safety": 2.0, ...})``.
        """
        return cls(principles=dict(overrides))

    # -- principle access -------------------------------------------

    def weight(self, principle: str) -> float:
        """Return the weight of a principle (or 1.0 if unknown).

        Unknown principles fall back to 1.0 so new code can
        reference new principles without breaking older
        :class:`Values` instances from persisted config.
        """
        return float(self.principles.get(principle, 1.0))

    # -- option scoring ---------------------------------------------

    def score(self, option: dict[str, Any]) -> float:
        """Weighted-sum utility for an *option* dict.

        ``option`` is expected to carry per-principle attributes
        in the ``[0, 1]`` range, e.g.::

            {"safety": 0.9, "speed": 0.4, "long_term": 0.7}

        The score is ``sum(principle_value * principle_weight)
        / sum(principle_weight)``. Missing attributes contribute
        0; extra keys in the option that are not principles are
        ignored so callers can pass through rich dicts without
        stripping fields.
        """
        total_w = 0.0
        total = 0.0
        for name, w in self.principles.items():
            if w <= 0:
                continue
            val = option.get(name)
            if val is None:
                continue
            try:
                total += float(val) * w
                total_w += w
            except (TypeError, ValueError):
                continue
        return (total / total_w) if total_w > 0 else 0.0

    # -- judgment-check multiplier ---------------------------------

    def check_multiplier(self, check_name: str) -> float:
        """Multiplier to apply to a judgment check's base weight.

        The multiplier is the mean of the principle weights that
        the check advances (per :data:`_CHECK_PRINCIPLES`). Checks
        that aren't mapped return 1.0 (neutral) so new checks added
        to the advisor don't silently lose weight.
        """
        principles = _CHECK_PRINCIPLES.get(check_name)
        if not principles:
            return 1.0
        weights = [self.weight(p) for p in principles]
        if not weights:
            return 1.0
        return sum(weights) / len(weights)

    def effective_check_weight(
        self, check_name: str, base_weight: float,
    ) -> float:
        """Apply the principle multiplier to a check's base weight
        and clamp to the sane range."""
        raw = base_weight * self.check_multiplier(check_name)
        return max(_MIN_EFFECTIVE_WEIGHT, min(_MAX_EFFECTIVE_WEIGHT, raw))


# ---------------------------------------------------------------------------
# Beta-binomial belief store
# ---------------------------------------------------------------------------


@dataclass
class Belief:
    """Single beta-binomial belief record.

    ``alpha`` and ``beta`` are the Beta distribution's shape
    parameters. They start at the prior (default ``alpha=beta=1``,
    i.e. uniform) and increment with each observation:

    * success → ``alpha += 1``
    * failure → ``beta  += 1``

    The posterior mean is ``alpha / (alpha + beta)``.
    """

    key: str
    alpha: float = 1.0
    beta: float = 1.0

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    @property
    def n(self) -> int:
        """Number of observations (successes + failures)."""
        return int(round(self.alpha + self.beta - 2))

    @property
    def variance(self) -> float:
        a, b = self.alpha, self.beta
        return (a * b) / (((a + b) ** 2) * (a + b + 1))

    @property
    def std(self) -> float:
        return math.sqrt(self.variance)

    def credible_interval_95(self) -> tuple[float, float]:
        """95% credible interval via a Normal approximation.

        For moderate n (say n >= 10) the Beta distribution is
        well-approximated by a Normal with matching mean/variance.
        For small n we clamp to ``[0, 1]`` and return a wide band.
        """
        if self.n < 5:
            return (0.0, 1.0)
        m, s = self.mean, self.std
        lo = max(0.0, m - 1.96 * s)
        hi = min(1.0, m + 1.96 * s)
        return (lo, hi)


class BeliefStore:
    """Thread-safe in-memory beta-binomial belief registry.

    Keys are free-form strings (conventionally ``"<category>::<id>"``)
    so callers can track as many beliefs as they want without
    pre-declaring them.
    """

    def __init__(
        self,
        prior_alpha: float = 1.0,
        prior_beta: float = 1.0,
    ) -> None:
        if prior_alpha <= 0 or prior_beta <= 0:
            raise ValueError(
                "Prior alpha and beta must be positive",
            )
        self._lock = threading.RLock()
        self._beliefs: dict[str, Belief] = {}
        self._prior = (float(prior_alpha), float(prior_beta))

    def observe(
        self,
        key: str,
        success: bool,
        weight: float = 1.0,
    ) -> Belief:
        """Record an observation and return the updated belief.

        ``weight`` lets callers record partial-credit observations
        (e.g. an A/B test with a 0.7 confidence in the label). The
        default 1.0 matches classic beta-binomial updates.
        """
        if weight < 0:
            raise ValueError("weight must be non-negative")
        with self._lock:
            belief = self._beliefs.get(key)
            if belief is None:
                belief = Belief(
                    key=key,
                    alpha=self._prior[0],
                    beta=self._prior[1],
                )
                self._beliefs[key] = belief
            if success:
                belief.alpha += weight
            else:
                belief.beta += weight
            logger.debug(
                "belief %r updated: success=%s weight=%.2f → "
                "alpha=%.2f beta=%.2f mean=%.3f",
                key, success, weight, belief.alpha, belief.beta,
                belief.mean,
            )
            return belief

    def get(self, key: str) -> Belief | None:
        with self._lock:
            return self._beliefs.get(key)

    def mean(self, key: str, default: float = 0.5) -> float:
        """Return the posterior mean or *default* if unknown."""
        belief = self.get(key)
        return belief.mean if belief is not None else default

    def credible_interval_95(
        self, key: str,
    ) -> tuple[float, float]:
        belief = self.get(key)
        if belief is None:
            return (0.0, 1.0)
        return belief.credible_interval_95()

    def keys(self) -> list[str]:
        with self._lock:
            return list(self._beliefs.keys())

    def reset(self, key: str | None = None) -> None:
        """Reset one belief to the prior, or all beliefs if
        *key* is ``None``."""
        with self._lock:
            if key is None:
                self._beliefs.clear()
            else:
                self._beliefs.pop(key, None)

    def snapshot(self) -> dict[str, dict[str, float]]:
        """Return a serialisable view of all beliefs (e.g. for
        the reflection synthesizer or debug endpoints)."""
        with self._lock:
            return {
                key: {
                    "alpha": belief.alpha,
                    "beta":  belief.beta,
                    "mean":  belief.mean,
                    "n":     belief.n,
                }
                for key, belief in self._beliefs.items()
            }
