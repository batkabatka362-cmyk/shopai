"""RuleBook quality gate — lift-based true-positive measurement.

Why this exists (PATH_TO_T2.md §2 P0-C, §4 60-day KPI):
the RuleBook auto-promotes proposed rules to ``active`` when
``applied_count ≥ min_evidence`` and ``win_rate_ema ≥ 0.60``. A
rule at 60% looks great in isolation — but if the *baseline*
win rate across every outcome in the book is already 65%, the
rule is actually a **false positive**: brain would have won
more by doing nothing.

We measure that with **lift**:

    lift = rule.win_rate_ema / baseline_win_rate_ema

A lift ≥ 1.2 means the rule genuinely helps.
A lift in [0.8, 1.2] is noise-band → uncertain.
A lift < 0.8 means the rule actively hurts — a false positive.

The verdict is reported per rule so the owner (and the
RuleBook self-cleanup in a later pass) can kill false
positives even when their raw ema passed the promotion
threshold.

Pure stdlib. Deterministic under a fixed ``rulebook`` ref.
Read-only — never mutates state.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


_LIFT_POSITIVE = 1.20
_LIFT_NEGATIVE = 0.80
_MIN_APPLIED_FOR_VERDICT = 3


@dataclass
class RuleQuality:
    """Per-rule lift + verdict."""

    rule_id: str
    origin: str
    pattern: str
    action: str
    status: str
    applied_count: int
    win_rate_ema: float
    lift: float
    verdict: str  # "true_positive" | "false_positive" | "uncertain" | "insufficient_data"
    baseline_win_rate: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "origin": self.origin,
            "pattern": self.pattern,
            "action": self.action,
            "status": self.status,
            "applied_count": self.applied_count,
            "win_rate_ema": round(self.win_rate_ema, 4),
            "lift": round(self.lift, 4),
            "verdict": self.verdict,
            "baseline_win_rate": round(
                self.baseline_win_rate, 4,
            ),
        }


@dataclass
class RuleBookQualityReport:
    """Aggregate quality read across the whole RuleBook."""

    total_rules: int
    applied_rules: int
    baseline_win_rate: float
    true_positives: int
    false_positives: int
    uncertain: int
    insufficient_data: int
    true_positive_rate: float  # active rules with lift ≥ 1.2
    rules: list[RuleQuality]

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_rules": self.total_rules,
            "applied_rules": self.applied_rules,
            "baseline_win_rate": round(
                self.baseline_win_rate, 4,
            ),
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "uncertain": self.uncertain,
            "insufficient_data": self.insufficient_data,
            "true_positive_rate": round(
                self.true_positive_rate, 4,
            ),
            "rules": [r.as_dict() for r in self.rules],
        }


def _baseline_win_rate(rules: list[Any]) -> float:
    """Weighted mean of win_rate_ema across rules that have
    been applied at least once. Falls back to 0.5 for an empty
    book."""
    total_applied = 0
    total_wins = 0.0
    for r in rules:
        applied = int(getattr(r, "applied_count", 0) or 0)
        if applied <= 0:
            continue
        ema = float(getattr(r, "win_rate_ema", 0.5) or 0.5)
        total_applied += applied
        total_wins += applied * ema
    if total_applied == 0:
        return 0.5
    return total_wins / total_applied


def _verdict_for_rule(
    rule: Any, baseline: float,
) -> tuple[str, float]:
    applied = int(getattr(rule, "applied_count", 0) or 0)
    if applied < _MIN_APPLIED_FOR_VERDICT:
        return ("insufficient_data", 0.0)
    ema = float(getattr(rule, "win_rate_ema", 0.5) or 0.5)
    if baseline <= 0:
        return ("uncertain", 0.0)
    lift = ema / baseline
    if lift >= _LIFT_POSITIVE:
        return ("true_positive", lift)
    if lift < _LIFT_NEGATIVE:
        return ("false_positive", lift)
    return ("uncertain", lift)


def evaluate_rulebook(
    rulebook: Any = None,
) -> RuleBookQualityReport:
    """Walk every rule in the book, compute lift vs the
    weighted-mean baseline, and bucket the verdicts.

    Dependency-injected so tests can pass a stub rulebook with
    ``.top_by_confidence(limit=...)`` returning synthetic rules.
    """
    if rulebook is None:
        from core.learning.rulebook import get_rulebook
        rulebook = get_rulebook()
    rules = list(
        rulebook.top_by_confidence(limit=10000),
    )
    baseline = _baseline_win_rate(rules)
    per_rule: list[RuleQuality] = []
    true_pos = false_pos = unc = insuff = 0
    applied_rules = 0
    for r in rules:
        applied = int(getattr(r, "applied_count", 0) or 0)
        if applied > 0:
            applied_rules += 1
        verdict, lift = _verdict_for_rule(r, baseline)
        if verdict == "true_positive":
            true_pos += 1
        elif verdict == "false_positive":
            false_pos += 1
        elif verdict == "uncertain":
            unc += 1
        else:
            insuff += 1
        per_rule.append(RuleQuality(
            rule_id=str(getattr(r, "rule_id", "")),
            origin=str(getattr(r, "origin", "")),
            pattern=str(getattr(r, "pattern", "")),
            action=str(getattr(r, "action", "")),
            status=str(getattr(r, "status", "")),
            applied_count=applied,
            win_rate_ema=float(
                getattr(r, "win_rate_ema", 0.0) or 0.0,
            ),
            lift=lift,
            verdict=verdict,
            baseline_win_rate=baseline,
        ))
    total = len(rules)
    # True-positive rate is the quality signal the owner cares
    # about: of the rules with enough evidence to judge, how
    # many genuinely lift outcomes?
    judged = true_pos + false_pos + unc
    tpr = (
        true_pos / judged if judged > 0 else 0.0
    )
    # Sort rules: active-with-highest-lift first, then lift-desc
    per_rule.sort(
        key=lambda q: (
            0 if q.status == "active" else 1,
            -q.lift,
        ),
    )
    return RuleBookQualityReport(
        total_rules=total,
        applied_rules=applied_rules,
        baseline_win_rate=baseline,
        true_positives=true_pos,
        false_positives=false_pos,
        uncertain=unc,
        insufficient_data=insuff,
        true_positive_rate=tpr,
        rules=per_rule,
    )
