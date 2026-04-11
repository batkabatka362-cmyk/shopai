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

import json
import math
import os
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
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

    Wave 6 #11 adds ``last_updated_at`` so the :class:`BeliefStore`
    can apply exponential forgetting between observations when
    configured with a ``half_life_seconds``. When decay is disabled
    the field is still updated but never read, so existing callers
    are unaffected.
    """

    key: str
    alpha: float = 1.0
    beta: float = 1.0
    last_updated_at: float | None = None

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

    Wave 6 #4: optional disk persistence
    ------------------------------------
    Supply ``persist_path`` to enable JSON snapshot persistence.
    On construction the store loads any existing snapshot from
    that path; on every :meth:`observe` call it atomically rewrites
    the snapshot so a crash can lose at most one observation. The
    file format is a flat JSON dict ``{key: {alpha, beta}}`` — the
    derived fields (``mean``, ``n``) are not stored since they
    recompute trivially from the two parameters.

    Wave 6 #11: exponential forgetting
    ----------------------------------
    Supply ``half_life_seconds`` to make evidence fade over time.
    Without decay, a belief that accrued 500 observations under
    regime A will drown out a new regime B for a very long time.
    With decay, each new observation first shrinks the existing
    ``(alpha - prior, beta - prior)`` excess by a factor of
    ``0.5 ** (elapsed / half_life)`` — so after one half-life the
    store "remembers" only half as much of the old evidence. The
    prior is never decayed, so a belief can never drop below its
    starting uncertainty. Decay is disabled by default (``None``)
    for backward compatibility with Waves 6 #4 and #5.
    """

    def __init__(
        self,
        prior_alpha: float = 1.0,
        prior_beta: float = 1.0,
        persist_path: str | os.PathLike | None = None,
        half_life_seconds: float | None = None,
    ) -> None:
        if prior_alpha <= 0 or prior_beta <= 0:
            raise ValueError(
                "Prior alpha and beta must be positive",
            )
        if half_life_seconds is not None:
            if not isinstance(half_life_seconds, (int, float)):
                raise ValueError(
                    "half_life_seconds must be numeric or None",
                )
            if half_life_seconds <= 0:
                raise ValueError(
                    "half_life_seconds must be positive when set",
                )
        self._lock = threading.RLock()
        self._beliefs: dict[str, Belief] = {}
        self._prior = (float(prior_alpha), float(prior_beta))
        self._half_life: float | None = (
            float(half_life_seconds)
            if half_life_seconds is not None
            else None
        )
        self._persist_path: Path | None = (
            Path(persist_path) if persist_path is not None else None
        )
        if self._persist_path is not None:
            self._load_from_disk()

    @property
    def half_life_seconds(self) -> float | None:
        return self._half_life

    def observe(
        self,
        key: str,
        success: bool,
        weight: float = 1.0,
        *,
        now: float | None = None,
    ) -> Belief:
        """Record an observation and return the updated belief.

        ``weight`` lets callers record partial-credit observations
        (e.g. an A/B test with a 0.7 confidence in the label). The
        default 1.0 matches classic beta-binomial updates.

        ``now`` is the wall-clock timestamp of the observation, used
        by the Wave 6 #11 decay path when the store is constructed
        with ``half_life_seconds``. It defaults to ``time.time()``
        and is exposed mostly for tests that want to drive the clock
        deterministically.
        """
        if weight < 0:
            raise ValueError("weight must be non-negative")
        import time as _time
        ts = float(now) if now is not None else _time.time()
        with self._lock:
            belief = self._beliefs.get(key)
            if belief is None:
                belief = Belief(
                    key=key,
                    alpha=self._prior[0],
                    beta=self._prior[1],
                    last_updated_at=ts,
                )
                self._beliefs[key] = belief
            else:
                # Wave 6 #11: exponentially forget the pre-existing
                # excess over the prior before adding the new
                # observation. Only applies when decay is enabled
                # AND the belief carries a timestamp from a prior
                # update — brand-new beliefs and pre-decay snapshots
                # simply start their clock here.
                if (
                    self._half_life is not None
                    and belief.last_updated_at is not None
                ):
                    elapsed = ts - float(belief.last_updated_at)
                    if elapsed > 0:
                        factor = 0.5 ** (elapsed / self._half_life)
                        prior_a, prior_b = self._prior
                        belief.alpha = prior_a + (
                            belief.alpha - prior_a
                        ) * factor
                        belief.beta = prior_b + (
                            belief.beta - prior_b
                        ) * factor
                belief.last_updated_at = ts
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
            # Wave 6 #4: persist-on-observe so a crash between
            # ticks loses at most the current update. Failure to
            # write is logged but never propagated — an unhealthy
            # disk must not take down the decision gate.
            if self._persist_path is not None:
                try:
                    self._save_to_disk_locked()
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "belief store: persist failed for %r: %s",
                        self._persist_path, exc,
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
            # Wave 6 #4: keep disk in sync with in-memory state.
            if self._persist_path is not None:
                try:
                    self._save_to_disk_locked()
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "belief store: persist failed on reset: %s", exc,
                    )

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

    # -- Wave 6 #4: disk persistence ----------------------------------

    @property
    def persist_path(self) -> Path | None:
        return self._persist_path

    def save(self) -> None:
        """Explicit snapshot write. Useful for graceful shutdown
        paths that want to persist on demand without waiting for
        the next observation. No-op when no persist path is set."""
        if self._persist_path is None:
            return
        with self._lock:
            self._save_to_disk_locked()

    def _save_to_disk_locked(self) -> None:
        """Atomically rewrite the snapshot file.

        Writes to a sibling ``*.tmp`` file first, then renames over
        the target. That matches what PolicyStore does and keeps
        readers from ever seeing a half-written file.
        Must be called under ``self._lock``.
        """
        assert self._persist_path is not None
        target = self._persist_path
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            key: {
                "alpha": b.alpha,
                "beta":  b.beta,
                # Wave 6 #11: round-trip the decay timestamp so a
                # restart doesn't reset the forgetting clock.
                # Older snapshots without this field load fine — we
                # just treat them as "no clock yet" and start fresh
                # on the next observe.
                **(
                    {"last_updated_at": b.last_updated_at}
                    if b.last_updated_at is not None
                    else {}
                ),
            }
            for key, b in self._beliefs.items()
        }
        # Use NamedTemporaryFile in the same directory so the final
        # rename is an atomic rename on the same filesystem.
        fd, tmp_name = tempfile.mkstemp(
            prefix=target.name + ".",
            suffix=".tmp",
            dir=str(target.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)
                fh.flush()
                try:
                    os.fsync(fh.fileno())
                except OSError:
                    # Some filesystems (tmpfs) don't support fsync.
                    pass
            os.replace(tmp_name, target)
        except Exception:
            # Best effort cleanup — the tmp file may still exist.
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    def _load_from_disk(self) -> None:
        """Populate the in-memory dict from an existing snapshot.

        A missing or unreadable file is treated as an empty store —
        we never crash the advisor because the belief file is bad.
        Malformed JSON, wrong shapes, and non-positive parameters
        are skipped with a warning; valid rows still load.
        """
        assert self._persist_path is not None
        path = self._persist_path
        if not path.exists():
            return
        try:
            with open(path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "belief store: could not read %r (%s) — starting empty",
                str(path), exc,
            )
            return
        if not isinstance(raw, dict):
            logger.warning(
                "belief store: snapshot at %r is not a dict — ignoring",
                str(path),
            )
            return
        loaded = 0
        for key, row in raw.items():
            if not isinstance(key, str) or not isinstance(row, dict):
                continue
            alpha = row.get("alpha")
            beta = row.get("beta")
            try:
                a = float(alpha)
                b = float(beta)
            except (TypeError, ValueError):
                continue
            if a <= 0 or b <= 0:
                continue
            ts = row.get("last_updated_at")
            try:
                ts_f = float(ts) if ts is not None else None
            except (TypeError, ValueError):
                ts_f = None
            self._beliefs[key] = Belief(
                key=key, alpha=a, beta=b, last_updated_at=ts_f,
            )
            loaded += 1
        logger.info(
            "belief store: loaded %d belief(s) from %r",
            loaded, str(path),
        )


# ---------------------------------------------------------------------------
# Wave 6 #5: process-wide default belief store
# ---------------------------------------------------------------------------
#
# JudgmentAdvisor instantiates its own BeliefStore when callers don't
# supply one. Historically that store was in-memory only, so each
# advisor had its own isolated belief state. Wave 6 #4 made the store
# persist-capable; Wave 6 #5 wires a single shared store into the
# production code path so every advisor (and the HTTP endpoint) sees
# the same persisted beliefs.
#
# Kept at module level so tests can:
#   - read/replace the singleton via ``get_default_belief_store`` /
#     ``set_default_belief_store``
#   - clear it with ``reset_default_belief_store`` between isolated runs


_DEFAULT_BELIEFS_PATH = os.path.join(
    os.path.dirname(__file__), ".state", "beliefs.json",
)

_default_belief_store: BeliefStore | None = None
_default_belief_store_lock = threading.Lock()


def get_default_belief_store() -> BeliefStore:
    """Return (constructing on first call) the process-wide belief store.

    The persist path is resolved in order:

    1. An earlier :func:`set_default_belief_store` call always wins
    2. Environment variable ``SHOPAI_BELIEFS_PATH``
    3. Module default ``core/mentality/.state/beliefs.json``

    The optional half-life (Wave 6 #11) is taken from
    ``SHOPAI_BELIEF_HALF_LIFE_SEC`` when set to a positive number;
    otherwise decay is disabled.

    Thread-safe. Falls back to an in-memory store if disk
    construction raises.
    """
    global _default_belief_store
    with _default_belief_store_lock:
        if _default_belief_store is None:
            path = os.environ.get(
                "SHOPAI_BELIEFS_PATH", _DEFAULT_BELIEFS_PATH,
            )
            half_life_env = os.environ.get(
                "SHOPAI_BELIEF_HALF_LIFE_SEC",
            )
            half_life: float | None = None
            if half_life_env is not None and half_life_env.strip():
                try:
                    parsed = float(half_life_env)
                    if parsed > 0:
                        half_life = parsed
                except (TypeError, ValueError):
                    logger.warning(
                        "get_default_belief_store: ignoring invalid "
                        "SHOPAI_BELIEF_HALF_LIFE_SEC=%r",
                        half_life_env,
                    )
            try:
                _default_belief_store = BeliefStore(
                    persist_path=path,
                    half_life_seconds=half_life,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "get_default_belief_store: persistent init failed "
                    "(%s) — falling back to in-memory",
                    exc,
                )
                _default_belief_store = BeliefStore(
                    half_life_seconds=half_life,
                )
        return _default_belief_store


def set_default_belief_store(store: BeliefStore) -> None:
    """Override the process-wide belief store (used by tests and
    by boot code that wants a non-default persist path)."""
    global _default_belief_store
    with _default_belief_store_lock:
        _default_belief_store = store


def reset_default_belief_store() -> None:
    """Drop the cached singleton so the next access re-creates it.

    Used by tests so one test run's persisted beliefs can't leak
    into another."""
    global _default_belief_store
    with _default_belief_store_lock:
        _default_belief_store = None
