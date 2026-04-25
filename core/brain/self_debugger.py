"""Self-debugger — hypothesise and test why the same phase keeps failing.

When a cycle phase has failed N times in a row with the same class of
exception, the brain should notice and try to fix its own behaviour,
not just log and move on. self_debugger:

  1. Watches phase_errors and invariant_monitor breaches through
     ``note(name, error)``.
  2. When a *repeat* pattern hits the threshold (default ≥ 3 in a
     row), emits a ``FailureCase`` that includes a structured
     fingerprint of the error.
  3. Matches that fingerprint against a registry of
     ``DiagnosticRule``s — each a (matcher, hypothesis, probe,
     remedy) quadruple. When a rule matches, ``diagnose()`` runs
     its probe, and if probe returns True, the remedy tag is
     surfaced for the controller / experience recorder to act on.

Out of the box we ship a few canonical rules:
  - "rate_limit" → likely too-fast calls → recommend backoff
  - "unauthorized" → stale token → recommend oauth refresh
  - "schema_drift" → payload mismatch → recommend contract check
  - "timeout" → network flake → recommend retry + circuit break

Callers can register their own rules too. No LLM — matching is pure
substring / regex, so the diagnosis is explainable and deterministic.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from utils.logger import get_logger


logger = get_logger("brain.self_debugger")


ProbeFn = Callable[[dict[str, Any]], bool]


@dataclass
class FailureCase:
    phase: str
    fingerprint: str
    repeat_count: int
    first_seen: float
    last_seen: float
    sample_error: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "fingerprint": self.fingerprint,
            "repeat_count": self.repeat_count,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "sample_error": self.sample_error,
        }


@dataclass
class DiagnosticRule:
    name: str
    match: Callable[[FailureCase], bool]
    hypothesis: str
    probe: ProbeFn | None = None
    remedy: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("DiagnosticRule.name required")

    def matches(self, case: FailureCase) -> bool:
        try:
            return bool(self.match(case))
        except Exception as exc:
            logger.debug("rule %s match raised: %s", self.name, exc)
            return False


@dataclass
class Diagnosis:
    case: FailureCase
    rule: str
    hypothesis: str
    confirmed: bool
    remedy: str
    ts: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "case": self.case.as_dict(),
            "rule": self.rule,
            "hypothesis": self.hypothesis,
            "confirmed": self.confirmed,
            "remedy": self.remedy,
            "ts": self.ts,
        }


# ── Fingerprinting ────────────────────────────────────────

_FP_TOKEN = re.compile(r"[0-9a-f]{8,}|\d{2,}")


def _fingerprint(error: str) -> str:
    """Strip numeric/hex noise so two 'HTTP 429' errors at different
    rate-limit windows produce the same fingerprint."""
    return _FP_TOKEN.sub("*", (error or "").lower()).strip()[:180]


# ── Debugger ──────────────────────────────────────────────

class SelfDebugger:
    def __init__(self, *, repeat_threshold: int = 3) -> None:
        if repeat_threshold < 2:
            raise ValueError("repeat_threshold must be ≥ 2")
        self._threshold = int(repeat_threshold)
        self._streaks: dict[tuple[str, str], FailureCase] = {}
        self._rules: list[DiagnosticRule] = []

    # ── Rule registration ────────────────────────────────

    def register(self, rule: DiagnosticRule) -> None:
        self._rules.append(rule)

    def rules(self) -> list[DiagnosticRule]:
        return list(self._rules)

    def register_defaults(self) -> None:
        self.register(DiagnosticRule(
            name="rate_limit",
            match=lambda c: (
                "rate" in c.fingerprint
                or "429" in c.sample_error
                or "too many" in c.fingerprint
            ),
            hypothesis="likely tripping an upstream rate limit",
            remedy="backoff_and_retry",
        ))
        self.register(DiagnosticRule(
            name="unauthorized",
            match=lambda c: (
                "401" in c.sample_error
                or "403" in c.sample_error
                or "unauthorized" in c.fingerprint
                or "forbidden" in c.fingerprint
            ),
            hypothesis="credential may be stale or scoped wrong",
            remedy="oauth_refresh",
        ))
        self.register(DiagnosticRule(
            name="schema_drift",
            match=lambda c: (
                "keyerror" in c.fingerprint
                or "missing" in c.fingerprint
                or "unexpected" in c.fingerprint
            ),
            hypothesis="payload schema may have shifted",
            remedy="contract_check",
        ))
        self.register(DiagnosticRule(
            name="timeout",
            match=lambda c: (
                "timeout" in c.fingerprint
                or "timed out" in c.fingerprint
            ),
            hypothesis="network flakiness; try again soon",
            remedy="retry_with_circuit_breaker",
        ))

    # ── Intake ────────────────────────────────────────────

    def note(
        self,
        phase: str,
        error: str,
    ) -> FailureCase | None:
        """Record one failure. Returns a FailureCase when the streak
        crosses the repeat threshold, else None."""
        if not phase:
            raise ValueError("phase required")
        fp = _fingerprint(error)
        key = (phase, fp)
        existing = self._streaks.get(key)
        now = time.time()
        if existing is None:
            self._streaks[key] = FailureCase(
                phase=phase, fingerprint=fp,
                repeat_count=1,
                first_seen=now, last_seen=now,
                sample_error=error[:240],
            )
            return None
        existing.repeat_count += 1
        existing.last_seen = now
        if existing.repeat_count >= self._threshold:
            return existing
        return None

    def reset(
        self,
        phase: str | None = None,
        fingerprint: str | None = None,
    ) -> int:
        if phase is None and fingerprint is None:
            n = len(self._streaks)
            self._streaks.clear()
            return n
        to_drop: list[tuple[str, str]] = []
        for key in self._streaks:
            p, fp = key
            if phase is not None and phase != p:
                continue
            if fingerprint is not None and fingerprint != fp:
                continue
            to_drop.append(key)
        for key in to_drop:
            del self._streaks[key]
        return len(to_drop)

    # ── Diagnose ─────────────────────────────────────────

    def diagnose(
        self,
        case: FailureCase,
        probe_context: dict[str, Any] | None = None,
    ) -> Diagnosis | None:
        probe_context = dict(probe_context or {})
        for rule in self._rules:
            if not rule.matches(case):
                continue
            confirmed = True
            if rule.probe is not None:
                try:
                    confirmed = bool(rule.probe(probe_context))
                except Exception as exc:
                    logger.debug("probe %s raised: %s", rule.name, exc)
                    confirmed = False
            return Diagnosis(
                case=case, rule=rule.name,
                hypothesis=rule.hypothesis,
                confirmed=confirmed,
                remedy=rule.remedy,
                ts=time.time(),
            )
        return None

    def stats(self) -> dict[str, Any]:
        return {
            "active_streaks": len(self._streaks),
            "rules": len(self._rules),
            "over_threshold": sum(
                1 for c in self._streaks.values()
                if c.repeat_count >= self._threshold
            ),
        }
