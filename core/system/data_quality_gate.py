"""Data quality gate — validate incoming payloads before use.

Every external webhook or API response used to flow into the
brain unchecked. A Shopify order with a missing ``currency``
field or a negative ``price`` silently poisoned downstream
analytics — world_model.update would still fold it, reward_model
would learn from it, drift_detector would flag the aggregate but
not the source.

DataQualityGate runs a declarative schema over every payload and
returns a QualityReport with:

  • status             → "pass" | "warn" | "fail"
  • issues[]           → one per failing rule
  • cleaned_payload    → payload with repairable issues fixed

Rules:

  required(field)                   — missing → fail
  type_check(field, type)           — wrong type → fail / coerce
  numeric_range(field, lo?, hi?)    — out of band → warn / clamp
  regex(field, pattern)             — no match → fail
  enum(field, allowed_values)       — not in set → fail
  length(field, min?, max?)         — string/list length check

Each rule declares a severity (fail / warn) and an optional
autocorrect fn so simple fixes (clamp numbers, strip whitespace,
lowercase enum) apply automatically without blocking the payload.

Pure stdlib. Deterministic. Zero LLM.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Literal


Severity = Literal["fail", "warn"]


@dataclass
class Issue:
    rule: str
    field: str
    severity: Severity
    detail: str = ""
    auto_fixed: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "field": self.field,
            "severity": self.severity,
            "detail": self.detail,
            "auto_fixed": self.auto_fixed,
        }


@dataclass
class QualityReport:
    status: Literal["pass", "warn", "fail"]
    issues: list[Issue] = field(default_factory=list)
    cleaned_payload: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "issues": [i.as_dict() for i in self.issues],
            "cleaned_payload": self.cleaned_payload,
        }


# ── Rule objects ───────────────────────────────────────────

@dataclass
class Rule:
    name: str
    field: str
    severity: Severity
    evaluator: Callable[[Any, dict[str, Any]], tuple[bool, str, Any]]


# Evaluator returns (ok, detail, repaired_value).
# When repaired_value is not None, the gate writes it back.


def required(field_: str) -> Rule:
    def eval_(v, payload):
        ok = field_ in payload and payload[field_] is not None
        return ok, "missing" if not ok else "", None
    return Rule(
        name="required", field=field_,
        severity="fail", evaluator=eval_,
    )


def type_check(
    field_: str, t: type, *, coerce: bool = True,
    severity: Severity = "fail",
) -> Rule:
    def eval_(v, payload):
        if field_ not in payload:
            return True, "", None
        val = payload[field_]
        if isinstance(val, t):
            return True, "", None
        if coerce:
            try:
                repaired = t(val)
                return True, f"coerced to {t.__name__}", repaired
            except (TypeError, ValueError):
                # Coerce failed — fall through to the wrong-type
                # report below so the caller still learns why.
                return False, f"wrong type {type(val).__name__}", None
        return False, f"wrong type {type(val).__name__}", None
    return Rule(
        name="type_check", field=field_,
        severity=severity, evaluator=eval_,
    )


def numeric_range(
    field_: str, lo: float | None = None, hi: float | None = None,
    *, clamp: bool = True, severity: Severity = "warn",
) -> Rule:
    def eval_(v, payload):
        if field_ not in payload:
            return True, "", None
        val = payload[field_]
        try:
            n = float(val)
        except (TypeError, ValueError):
            return False, "non-numeric", None
        out = n
        if lo is not None and n < lo:
            out = lo
        if hi is not None and n > hi:
            out = hi
        if out == n:
            return True, "", None
        if clamp:
            return True, f"clamped {n:.3g}→{out:.3g}", out
        return False, f"out of [{lo}, {hi}]", None
    return Rule(
        name="numeric_range", field=field_,
        severity=severity, evaluator=eval_,
    )


def regex(
    field_: str, pattern: str, *,
    severity: Severity = "fail",
) -> Rule:
    compiled = re.compile(pattern)
    def eval_(v, payload):
        if field_ not in payload:
            return True, "", None
        val = payload[field_]
        if not isinstance(val, str):
            return False, "not a string", None
        if compiled.search(val):
            return True, "", None
        return False, f"does not match {pattern}", None
    return Rule(
        name="regex", field=field_,
        severity=severity, evaluator=eval_,
    )


def enum(
    field_: str, allowed: Iterable[Any],
    *, case_fix: bool = True, severity: Severity = "fail",
) -> Rule:
    allowed_set = set(allowed)
    allowed_lower = (
        {str(a).lower() for a in allowed_set}
        if case_fix else set()
    )
    def eval_(v, payload):
        if field_ not in payload:
            return True, "", None
        val = payload[field_]
        if val in allowed_set:
            return True, "", None
        if case_fix and isinstance(val, str):
            lower = val.lower()
            if lower in allowed_lower:
                for a in allowed_set:
                    if str(a).lower() == lower:
                        return True, f"case fixed '{val}'→'{a}'", a
        return False, (
            f"not in {sorted(map(str, allowed_set))}"
        ), None
    return Rule(
        name="enum", field=field_,
        severity=severity, evaluator=eval_,
    )


def length(
    field_: str,
    min_len: int | None = None,
    max_len: int | None = None,
    severity: Severity = "warn",
) -> Rule:
    def eval_(v, payload):
        if field_ not in payload:
            return True, "", None
        val = payload[field_]
        if not hasattr(val, "__len__"):
            return False, "not sized", None
        n = len(val)
        if min_len is not None and n < min_len:
            return False, f"len {n} < {min_len}", None
        if max_len is not None and n > max_len:
            return False, f"len {n} > {max_len}", None
        return True, "", None
    return Rule(
        name="length", field=field_,
        severity=severity, evaluator=eval_,
    )


# ── Gate ───────────────────────────────────────────────────

class DataQualityGate:
    def __init__(self, rules: Iterable[Rule] | None = None) -> None:
        self._rules: list[Rule] = list(rules or [])

    def add(self, rule: Rule) -> None:
        self._rules.append(rule)

    def add_many(self, rules: Iterable[Rule]) -> None:
        self._rules.extend(rules)

    def rules(self) -> list[Rule]:
        return list(self._rules)

    def check(self, payload: dict[str, Any]) -> QualityReport:
        cleaned = dict(payload)
        issues: list[Issue] = []
        has_fail = False
        has_warn = False
        for rule in self._rules:
            try:
                ok, detail, repaired = rule.evaluator(
                    cleaned.get(rule.field), cleaned,
                )
            except Exception as exc:
                issues.append(Issue(
                    rule=rule.name, field=rule.field,
                    severity="fail",
                    detail=f"evaluator crashed: {exc}",
                ))
                has_fail = True
                continue
            if repaired is not None:
                cleaned[rule.field] = repaired
                issues.append(Issue(
                    rule=rule.name, field=rule.field,
                    severity="warn", detail=detail,
                    auto_fixed=True,
                ))
                has_warn = True
                continue
            if ok:
                continue
            issues.append(Issue(
                rule=rule.name, field=rule.field,
                severity=rule.severity, detail=detail,
            ))
            if rule.severity == "fail":
                has_fail = True
            else:
                has_warn = True
        status: Literal["pass", "warn", "fail"]
        if has_fail:
            status = "fail"
        elif has_warn:
            status = "warn"
        else:
            status = "pass"
        return QualityReport(
            status=status, issues=issues,
            cleaned_payload=cleaned,
        )
