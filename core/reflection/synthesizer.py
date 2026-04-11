"""ReflectionSynthesizer — mine error memories, promote learned rules.

Wave 2 #5 closes the one-way-learning gap: pre-fix, the
controller wrote error records into memory but no subsystem
ever read them back to turn recurring failures into policy.
The synthesizer is that reader. It walks a pool of
:class:`core.memory.quality_engine.MemoryRecord` observations,
groups them by signature, and when a pattern reaches a
configurable confidence threshold it builds a SOFT
:class:`engines.meta_governance.policy_store.PolicyRule` and
calls :meth:`PolicyStore.promote_soft_rule`. The rule then
participates in the tiered evaluation pipeline with no further
human intervention.

Design notes
------------

**Signature-based grouping.** A pattern is any set of error
records that share a stable ``signature`` — usually the
``kind`` plus a normalised chunk of the error message. The
synthesizer doesn't try to cluster by embedding; the goal is
*transparent* learning, so operators can trace the exact text
that produced each rule.

**Confidence = n / (n + k).** Simple Laplace smoothing with a
``smoothing`` parameter so a single occurrence doesn't
immediately promote, and a rule's confidence climbs gracefully
with each new matching error. The default promotion threshold
(``0.75`` with 3+ occurrences) matches the plan's "n ≥ 3 in
window" directive — tunable for tests.

**Idempotency.** The synthesizer keeps a ledger of
already-promoted signatures so subsequent runs over the same
error window don't spam the policy store with duplicate
promotions. Operators can clear the ledger via
:meth:`ReflectionSynthesizer.forget`.

**No I/O.** The synthesizer is pure Python over a
:class:`PolicyStore` reference and the caller-supplied error
pool. Integration with the controller is a single line in the
post-cycle hook.
"""
from __future__ import annotations

import hashlib
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from core.memory.quality_engine import (
    MemoryClass,
    MemoryRecord,
    classify,
)
from engines.meta_governance.policy_store import (
    PolicyRule,
    PolicyStore,
    PolicyTier,
    PolicyVerdict,
    get_default_store,
)
from utils.logger import get_logger

logger = get_logger("reflection.synthesizer")


# ---------------------------------------------------------------------------
# Pattern + report dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ErrorPattern:
    """A single mined error signature and its aggregated stats."""

    signature:     str
    kind:          str
    sample_text:   str
    occurrences:   int
    first_seen:    float
    last_seen:     float
    confidence:    float

    def as_dict(self) -> dict[str, Any]:
        return {
            "signature":   self.signature,
            "kind":        self.kind,
            "sample_text": self.sample_text,
            "occurrences": self.occurrences,
            "first_seen":  self.first_seen,
            "last_seen":   self.last_seen,
            "confidence":  self.confidence,
        }


@dataclass
class SynthesisReport:
    """Outcome of a single :meth:`ReflectionSynthesizer.run` call.

    ``patterns_total`` counts every signature seen; ``patterns_promoted``
    counts only those that both crossed the confidence threshold AND
    hadn't been promoted previously. ``rule_ids`` holds the ids of the
    new SOFT rules so callers can surface them in cycle reports.
    """

    patterns_total:     int
    patterns_promoted:  int
    patterns:           list[ErrorPattern] = field(default_factory=list)
    rule_ids:           list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "patterns_total":    self.patterns_total,
            "patterns_promoted": self.patterns_promoted,
            "patterns":          [p.as_dict() for p in self.patterns],
            "rule_ids":          self.rule_ids,
        }


# ---------------------------------------------------------------------------
# Signature extraction
# ---------------------------------------------------------------------------


_NUMBER_RE = re.compile(r"\d+")
_HEX_RE = re.compile(r"0x[0-9a-fA-F]+")
_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)
_WS_RE = re.compile(r"\s+")


def _extract_text(record: MemoryRecord) -> str:
    """Pull a representative string out of a record.

    Checks ``payload["message"]``, ``payload["error"]``, and
    ``payload["description"]`` in order, then falls back to
    the flattened payload. Missing everything yields the
    record kind.
    """
    p = record.payload or {}
    for key in ("message", "error", "description", "text"):
        val = p.get(key)
        if isinstance(val, str) and val:
            return val
    if p:
        parts: list[str] = []
        for k, v in p.items():
            parts.append(f"{k}={v}")
        return " ".join(parts)
    return record.kind


def _normalise_for_signature(text: str) -> str:
    """Collapse volatile tokens so different error instances share
    the same signature.

    Replaces UUIDs, hex addresses, and arbitrary numbers with
    placeholders, lowercases, and collapses whitespace. Two
    errors that differ only in id or latency-number end up with
    the same normalised form — which is exactly the grouping we
    want for pattern mining.
    """
    t = text.lower()
    t = _UUID_RE.sub("<uuid>", t)
    t = _HEX_RE.sub("<hex>", t)
    t = _NUMBER_RE.sub("<n>", t)
    t = _WS_RE.sub(" ", t).strip()
    return t


def _signature(kind: str, text: str) -> str:
    """Deterministic signature = kind + blake2b(normalised_text).

    The hash keeps signatures short without sacrificing
    collision resistance — a single hex digest is plenty for a
    few hundred patterns per window.
    """
    normalised = _normalise_for_signature(text)
    digest = hashlib.blake2b(normalised.encode("utf-8"), digest_size=8).hexdigest()
    return f"{kind}:{digest}"


# ---------------------------------------------------------------------------
# Synthesizer
# ---------------------------------------------------------------------------


RuleBuilder = Callable[[ErrorPattern], PolicyRule | None]


def _default_rule_builder(pattern: ErrorPattern) -> PolicyRule:
    """Build a SOFT BLOCK rule that fires on the same signature.

    The matcher inspects ``action["kind"]`` and ``action``-level
    text fields; a real ShopAI action schema would hook in a
    richer matcher, but the default lets tests verify the
    promotion pipeline end-to-end without stubbing anything.
    """
    sig = pattern.signature
    expected_kind = pattern.kind
    norm_target = _normalise_for_signature(pattern.sample_text)

    def matcher(action: dict[str, Any], ctx: dict[str, Any]) -> bool:
        if action.get("kind") != expected_kind:
            return False
        # Compare on any text-ish field present on the action.
        for key in ("message", "error", "description", "text"):
            val = action.get(key)
            if isinstance(val, str) and _normalise_for_signature(val) == norm_target:
                return True
        return False

    return PolicyRule(
        rule_id=f"learned::{sig}",
        name=f"auto-blocked pattern {sig}",
        tier=PolicyTier.SOFT,
        source="learned",
        description=(
            f"Auto-promoted from {pattern.occurrences} matching error "
            f"records (confidence={pattern.confidence:.2f})."
        ),
        matcher=matcher,
        verdict=PolicyVerdict.BLOCK,
    )


class ReflectionSynthesizer:
    """Mine error records and promote durable patterns to SOFT rules.

    Parameters
    ----------
    policy_store :
        Target store for ``promote_soft_rule`` calls. Defaults to
        the module-level default store so controller integration
        is one-line.
    min_occurrences :
        Patterns must reach this count before being eligible for
        promotion. Default 3.
    min_confidence :
        Confidence threshold (Laplace-smoothed success fraction).
        Default 0.75.
    smoothing :
        Laplace smoothing constant; larger values slow the
        confidence climb. Default 1.
    rule_builder :
        Callable that turns a promoted :class:`ErrorPattern` into
        a :class:`PolicyRule`. Defaults to
        :func:`_default_rule_builder`.
    """

    def __init__(
        self,
        *,
        policy_store: PolicyStore | None = None,
        min_occurrences: int = 3,
        min_confidence: float = 0.75,
        smoothing: float = 1.0,
        rule_builder: RuleBuilder | None = None,
    ) -> None:
        if min_occurrences < 1:
            raise ValueError("min_occurrences must be >= 1")
        if not 0.0 <= min_confidence <= 1.0:
            raise ValueError("min_confidence must be in [0, 1]")
        if smoothing < 0:
            raise ValueError("smoothing must be non-negative")
        self._store = policy_store or get_default_store()
        self._min_occ = min_occurrences
        self._min_conf = min_confidence
        self._smoothing = smoothing
        self._rule_builder = rule_builder or _default_rule_builder
        self._lock = threading.RLock()
        self._promoted: set[str] = set()
        self._last_run_at: float | None = None

    # -- introspection ----------------------------------------------

    @property
    def promoted_signatures(self) -> list[str]:
        with self._lock:
            return sorted(self._promoted)

    @property
    def last_run_at(self) -> float | None:
        return self._last_run_at

    def forget(self, signature: str | None = None) -> None:
        """Drop a signature (or all of them) from the "already promoted"
        ledger so the next run re-promotes it.

        Useful after an operator deletes a SOFT rule and wants the
        synthesizer to repopulate it organically.
        """
        with self._lock:
            if signature is None:
                self._promoted.clear()
            else:
                self._promoted.discard(signature)

    # -- mining -----------------------------------------------------

    def mine(
        self,
        records: Iterable[MemoryRecord],
    ) -> list[ErrorPattern]:
        """Walk *records* and aggregate matching error signatures.

        Non-ERROR records (per :func:`classify`) are skipped so
        callers can hand over a mixed stream without filtering
        first.
        """
        buckets: dict[str, dict[str, Any]] = {}
        for rec in records:
            if classify(rec) != MemoryClass.ERROR:
                continue
            text = _extract_text(rec)
            sig = _signature(rec.kind, text)
            bucket = buckets.get(sig)
            if bucket is None:
                buckets[sig] = {
                    "kind":        rec.kind,
                    "sample_text": text,
                    "occurrences": 1,
                    "first_seen":  rec.created_at,
                    "last_seen":   rec.created_at,
                }
            else:
                bucket["occurrences"] += 1
                if rec.created_at < bucket["first_seen"]:
                    bucket["first_seen"] = rec.created_at
                if rec.created_at > bucket["last_seen"]:
                    bucket["last_seen"] = rec.created_at

        patterns: list[ErrorPattern] = []
        for sig, data in buckets.items():
            n = data["occurrences"]
            # Laplace smoothing: n / (n + smoothing)
            conf = n / (n + self._smoothing) if (n + self._smoothing) > 0 else 0.0
            patterns.append(ErrorPattern(
                signature=sig,
                kind=data["kind"],
                sample_text=data["sample_text"],
                occurrences=n,
                first_seen=data["first_seen"],
                last_seen=data["last_seen"],
                confidence=conf,
            ))
        # Deterministic order: most-seen first, then signature
        patterns.sort(key=lambda p: (-p.occurrences, p.signature))
        return patterns

    # -- promotion --------------------------------------------------

    def run(
        self,
        records: Iterable[MemoryRecord],
    ) -> SynthesisReport:
        """Mine *records* and promote any qualifying patterns.

        Patterns that crossed both ``min_occurrences`` AND
        ``min_confidence`` and haven't been promoted before are
        fed through ``rule_builder`` and registered on the
        policy store as SOFT rules. Subsequent runs skip them
        (unless :meth:`forget` is called first).
        """
        patterns = self.mine(records)
        report = SynthesisReport(
            patterns_total=len(patterns),
            patterns_promoted=0,
            patterns=patterns,
        )
        with self._lock:
            for pattern in patterns:
                if pattern.occurrences < self._min_occ:
                    continue
                if pattern.confidence < self._min_conf:
                    continue
                if pattern.signature in self._promoted:
                    continue
                try:
                    rule = self._rule_builder(pattern)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "rule_builder failed for %s: %s",
                        pattern.signature, exc,
                    )
                    continue
                if rule is None:
                    continue
                try:
                    rule_id = self._store.promote_soft_rule(rule)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "policy_store.promote_soft_rule failed for %s: %s",
                        pattern.signature, exc,
                    )
                    continue
                self._promoted.add(pattern.signature)
                report.rule_ids.append(rule_id)
                report.patterns_promoted += 1
                logger.info(
                    "Reflection: promoted pattern %s to SOFT rule %s "
                    "(occ=%d conf=%.2f)",
                    pattern.signature, rule_id,
                    pattern.occurrences, pattern.confidence,
                )
            self._last_run_at = time.time()
        return report


__all__ = [
    "ErrorPattern",
    "SynthesisReport",
    "ReflectionSynthesizer",
]
