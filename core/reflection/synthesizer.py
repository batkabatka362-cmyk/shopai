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
import json
import os
import re
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
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

    Wave 6 #17 adds ``pending_patterns`` — patterns that cleared at
    least one of the two promotion gates (min_occurrences OR
    min_confidence) but not both. These are "near miss" patterns
    that give operators early warning of emerging error trends
    before they fully qualify.
    """

    patterns_total:     int
    patterns_promoted:  int
    patterns:           list[ErrorPattern] = field(default_factory=list)
    rule_ids:           list[str] = field(default_factory=list)
    pending_patterns:   list[ErrorPattern] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "patterns_total":    self.patterns_total,
            "patterns_promoted": self.patterns_promoted,
            "patterns":          [p.as_dict() for p in self.patterns],
            "rule_ids":          self.rule_ids,
            "pending_patterns":  [p.as_dict() for p in self.pending_patterns],
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
    persist_path :
        Optional path to a JSONL file used to checkpoint every
        promoted :class:`ErrorPattern`. On construction the file
        is replayed so learned rules survive process restarts.
        Wave 6 #6. When ``None``, the synthesizer stays purely
        in-memory and behaves exactly like pre-Wave-6 instances.
    """

    def __init__(
        self,
        *,
        policy_store: PolicyStore | None = None,
        min_occurrences: int = 3,
        min_confidence: float = 0.75,
        smoothing: float = 1.0,
        rule_builder: RuleBuilder | None = None,
        persist_path: str | os.PathLike | None = None,
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
        # Wave 6 #7: keep the full ErrorPattern alongside the
        # signature so operators can inspect what the gate has
        # learned without scraping the JSONL ledger.
        self._pattern_cache: dict[str, ErrorPattern] = {}
        self._last_run_at: float | None = None
        # Wave 6 #18: cache the most recent SynthesisReport so
        # the /api/reflection endpoint can surface pending patterns
        # from the last run without re-mining.
        self._last_report: SynthesisReport | None = None
        self._persist_path: Path | None = (
            Path(persist_path) if persist_path is not None else None
        )
        if self._persist_path is not None:
            self._rehydrate_from_disk()

    # -- introspection ----------------------------------------------

    @property
    def promoted_signatures(self) -> list[str]:
        with self._lock:
            return sorted(self._promoted)

    @property
    def last_run_at(self) -> float | None:
        return self._last_run_at

    @property
    def persist_path(self) -> Path | None:
        return self._persist_path

    @property
    def last_report(self) -> SynthesisReport | None:
        """The most recent :meth:`run` result, or ``None`` before
        the first run. Used by ``/api/reflection`` to surface
        pending patterns without re-mining."""
        return self._last_report

    def config(self) -> dict[str, Any]:
        """Return the synthesizer's tuning parameters.

        Wave 6 #16: operators investigating "why didn't this
        pattern promote?" need to see the bar — min_occurrences,
        min_confidence, smoothing — without reading the source.
        Surfaced through ``/api/reflection`` as a top-level
        ``config`` key.
        """
        return {
            "min_occurrences": self._min_occ,
            "min_confidence":  self._min_conf,
            "smoothing":       self._smoothing,
            "persist_path":    str(self._persist_path or ""),
        }

    def snapshot(self) -> list[dict[str, Any]]:
        """Return every learned pattern as a list of dicts.

        Wave 6 #7: exposes the in-memory pattern cache so the
        dashboard (and any ad-hoc caller) can render the learned
        rules without parsing the JSONL ledger. Each row is the
        same shape :class:`ErrorPattern.as_dict` produces, plus a
        ``rule_id`` derived from the signature so operators can
        cross-reference with the policy store audit log.

        The list is sorted by ``last_seen`` descending so the most
        recently-matched patterns surface first.
        """
        with self._lock:
            rows = [p.as_dict() for p in self._pattern_cache.values()]
        for row in rows:
            row["rule_id"] = f"learned::{row['signature']}"
        rows.sort(key=lambda r: r.get("last_seen", 0.0), reverse=True)
        return rows

    def forget(self, signature: str | None = None) -> None:
        """Drop a signature (or all of them) from the "already promoted"
        ledger so the next run re-promotes it.

        Useful after an operator deletes a SOFT rule and wants the
        synthesizer to repopulate it organically.
        """
        with self._lock:
            if signature is None:
                self._promoted.clear()
                self._pattern_cache.clear()
            else:
                self._promoted.discard(signature)
                self._pattern_cache.pop(signature, None)

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
                meets_occ = pattern.occurrences >= self._min_occ
                meets_conf = pattern.confidence >= self._min_conf
                if not meets_occ or not meets_conf:
                    # Wave 6 #17: track near-miss patterns that
                    # cleared one gate but not both. Already-
                    # promoted patterns are not pending (they
                    # graduated).
                    if (
                        (meets_occ or meets_conf)
                        and pattern.signature not in self._promoted
                    ):
                        report.pending_patterns.append(pattern)
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
                self._pattern_cache[pattern.signature] = pattern
                report.rule_ids.append(rule_id)
                report.patterns_promoted += 1
                logger.info(
                    "Reflection: promoted pattern %s to SOFT rule %s "
                    "(occ=%d conf=%.2f)",
                    pattern.signature, rule_id,
                    pattern.occurrences, pattern.confidence,
                )
                # Wave 6 #6: append to the promoted-patterns ledger
                # so the rule survives a restart. Failure is logged
                # and swallowed — a broken disk must not take down
                # the reflection pipeline.
                if self._persist_path is not None:
                    try:
                        self._append_to_ledger(pattern)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "reflection ledger append failed for %s: %s",
                            pattern.signature, exc,
                        )
            self._last_run_at = time.time()
            self._last_report = report
        return report

    # -- Wave 6 #6: ledger persistence --------------------------------

    def _append_to_ledger(self, pattern: ErrorPattern) -> None:
        """Append one promoted pattern to the JSONL ledger.

        The file is plain append-only JSONL — one pattern per
        line. Rehydration replays the whole file, so a corrupt
        trailing line just loses the latest entry and the earlier
        state is still intact.
        """
        assert self._persist_path is not None
        target = self._persist_path
        target.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "signature":   pattern.signature,
            "kind":        pattern.kind,
            "sample_text": pattern.sample_text,
            "occurrences": pattern.occurrences,
            "first_seen":  pattern.first_seen,
            "last_seen":   pattern.last_seen,
            "confidence":  pattern.confidence,
        }
        line = json.dumps(row) + "\n"
        with open(target, "a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                # tmpfs / ramdisks / network fs may not support fsync
                pass

    # -- Wave 6 #9: learned-rule decay --------------------------------

    def decay_stale_rules(
        self,
        max_idle_seconds: float,
        *,
        now: float | None = None,
    ) -> list[str]:
        """Drop learned rules that have been idle for too long.

        A rule is *stale* when its last meaningful activity is
        older than ``now - max_idle_seconds``. "Last activity" is
        the policy-store ``last_matched_at`` counter (Wave 6 #8)
        if present, else the pattern's own ``last_seen`` timestamp
        — so a rule that never fires but was learned recently is
        still kept until its own learning window lapses.

        For each stale signature the rule is removed from the
        attached policy store, the signature is dropped from
        ``_promoted`` and ``_pattern_cache``, and (if persistence
        is enabled) the ledger file is atomically rewritten with
        the surviving patterns. Exceptions from any single step
        are logged and swallowed — decay must never crash the
        reflection loop.

        Returns the list of removed signatures.
        """
        if max_idle_seconds < 0:
            raise ValueError("max_idle_seconds must be non-negative")
        now = now if now is not None else time.time()
        threshold = now - max_idle_seconds

        removed: list[str] = []
        with self._lock:
            # Work off a copy so we can mutate _pattern_cache safely.
            for signature, pattern in list(self._pattern_cache.items()):
                rule_id = f"learned::{signature}"
                last_active = self._last_activity_for(rule_id, pattern)
                if last_active >= threshold:
                    continue
                try:
                    self._store.remove(rule_id)
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        "decay: store.remove failed for %s: %s",
                        rule_id, exc,
                    )
                self._promoted.discard(signature)
                self._pattern_cache.pop(signature, None)
                removed.append(signature)
            if removed and self._persist_path is not None:
                try:
                    self._rewrite_ledger_locked()
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "reflection ledger rewrite after decay failed: %s",
                        exc,
                    )
        if removed:
            logger.info(
                "reflection decay: retired %d stale learned rule(s) "
                "(max_idle=%.0fs)",
                len(removed), max_idle_seconds,
            )
        return removed

    def _last_activity_for(
        self, rule_id: str, pattern: ErrorPattern,
    ) -> float:
        """Resolve the best-available "last activity" timestamp
        for a learned rule, falling back to the pattern's own
        ``last_seen`` when the store has no stats for it."""
        try:
            get_stats = getattr(self._store, "get_rule_stats", None)
            if get_stats is not None:
                stats = get_stats(rule_id)
                if stats and stats.get("last_matched_at") is not None:
                    return float(stats["last_matched_at"])
        except Exception as exc:  # noqa: BLE001
            logger.debug("decay: stats lookup failed for %s: %s", rule_id, exc)
        # No store stats → rule has never matched. Use the
        # learning-time recency of the pattern itself.
        return float(pattern.last_seen or pattern.first_seen or 0.0)

    def _rewrite_ledger_locked(self) -> None:
        """Atomically rewrite the persistent ledger to reflect the
        current ``_pattern_cache``.

        Called only after :meth:`decay_stale_rules` shrinks the
        cache. The append-only file is replaced by a fresh one
        containing exactly the surviving patterns — this is the
        only operation that shrinks the ledger, so the invariant
        "ledger = latest snapshot of _pattern_cache" holds.
        Written via ``tempfile.mkstemp`` + ``os.replace`` so a
        crash mid-rewrite leaves the previous ledger intact.
        """
        assert self._persist_path is not None
        target = self._persist_path
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=target.name + ".",
            suffix=".tmp",
            dir=str(target.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                for pattern in self._pattern_cache.values():
                    row = {
                        "signature":   pattern.signature,
                        "kind":        pattern.kind,
                        "sample_text": pattern.sample_text,
                        "occurrences": pattern.occurrences,
                        "first_seen":  pattern.first_seen,
                        "last_seen":   pattern.last_seen,
                        "confidence":  pattern.confidence,
                    }
                    fh.write(json.dumps(row) + "\n")
                fh.flush()
                try:
                    os.fsync(fh.fileno())
                except OSError:
                    pass
            os.replace(tmp_name, str(target))
        except Exception:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass
            raise

    def _rehydrate_from_disk(self) -> None:
        """Replay the promoted-patterns ledger at startup.

        Each line is a JSON dict matching :class:`ErrorPattern`.
        For every row we reconstruct the ErrorPattern, rebuild
        the rule via ``self._rule_builder``, re-register it on the
        policy store, and mark the signature as promoted so a
        subsequent mine over recent records won't re-emit the
        same promotion. Malformed rows are skipped with a warning
        and the rest of the ledger still loads.

        A missing file is a no-op — fresh deploy.
        """
        assert self._persist_path is not None
        path = self._persist_path
        if not path.exists():
            return
        loaded = 0
        skipped = 0
        try:
            with open(path, "r", encoding="utf-8") as fh:
                lines = fh.readlines()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "reflection ledger: could not read %r (%s) — "
                "starting fresh",
                str(path), exc,
            )
            return
        for raw_line in lines:
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                row = json.loads(raw_line)
            except Exception:
                skipped += 1
                continue
            if not isinstance(row, dict):
                skipped += 1
                continue
            try:
                pattern = ErrorPattern(
                    signature=str(row["signature"]),
                    kind=str(row["kind"]),
                    sample_text=str(row["sample_text"]),
                    occurrences=int(row["occurrences"]),
                    first_seen=float(row.get("first_seen", 0.0)),
                    last_seen=float(row.get("last_seen", 0.0)),
                    confidence=float(row.get("confidence", self._min_conf)),
                )
            except (KeyError, TypeError, ValueError):
                skipped += 1
                continue
            if pattern.signature in self._promoted:
                # Duplicate — the ledger grew past this row earlier
                # but the signature is already marked. Skip.
                continue
            try:
                rule = self._rule_builder(pattern)
                if rule is not None:
                    self._store.promote_soft_rule(rule)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "reflection ledger: replay failed for %s: %s",
                    pattern.signature, exc,
                )
                skipped += 1
                continue
            self._promoted.add(pattern.signature)
            self._pattern_cache[pattern.signature] = pattern
            loaded += 1
        logger.info(
            "reflection ledger: rehydrated %d pattern(s) from %r (%d skipped)",
            loaded, str(path), skipped,
        )


# ---------------------------------------------------------------------------
# Wave 6 #6: process-wide default synthesizer
# ---------------------------------------------------------------------------
#
# The autonomous controller was constructing a throwaway synthesizer
# per run_cycle() call, so the in-memory ``_promoted`` ledger was
# reset on every boot. Combined with an in-memory-only policy store,
# learned rules vanished on restart. Wave 6 #6 adds persistence to
# the synthesizer and a module-level default that reads its path
# from the environment so the controller — and anyone else who wants
# to participate in the same learning loop — can share one store.


_DEFAULT_REFLECTION_PATH = os.path.join(
    os.path.dirname(__file__), ".state", "reflection_ledger.jsonl",
)

_default_synth: "ReflectionSynthesizer | None" = None
_default_synth_lock = threading.Lock()


def get_default_synthesizer() -> "ReflectionSynthesizer":
    """Return the process-wide :class:`ReflectionSynthesizer`.

    Path resolution:
      1. earlier :func:`set_default_synthesizer` always wins
      2. ``SHOPAI_REFLECTION_PATH`` env var
      3. module default at ``core/reflection/.state/reflection_ledger.jsonl``
    """
    global _default_synth
    with _default_synth_lock:
        if _default_synth is None:
            path = os.environ.get(
                "SHOPAI_REFLECTION_PATH", _DEFAULT_REFLECTION_PATH,
            )
            try:
                _default_synth = ReflectionSynthesizer(persist_path=path)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "get_default_synthesizer: persistent init failed "
                    "(%s) — falling back to in-memory",
                    exc,
                )
                _default_synth = ReflectionSynthesizer()
        return _default_synth


def set_default_synthesizer(synth: "ReflectionSynthesizer") -> None:
    """Override the process-wide synthesizer (used by tests)."""
    global _default_synth
    with _default_synth_lock:
        _default_synth = synth


def reset_default_synthesizer() -> None:
    """Clear the cached singleton so the next access rebuilds it."""
    global _default_synth
    with _default_synth_lock:
        _default_synth = None


__all__ = [
    "ErrorPattern",
    "SynthesisReport",
    "ReflectionSynthesizer",
    "get_default_synthesizer",
    "set_default_synthesizer",
    "reset_default_synthesizer",
]
