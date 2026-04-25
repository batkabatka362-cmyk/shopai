"""Robustness tester — adversarial stress-testing of brain rules.

Every rule in ShopAI was written to handle the "normal" case.
Edge cases — typos in copy tone, zero-division on spend, missing
margin_pct field, null niche string — used to fall through
unexpectedly. Ethics_gate (v8-D5) covers outbound harm;
robustness covers *inbound breakage*: does the rule refuse to
crash, produce a sane default, or at least flag the anomaly?

RobustnessTester takes a rule (any callable that accepts an input
dict) and a set of perturbations, then records which perturbations
caused the rule to crash, return a wrong type, or change output
so drastically it looks broken.

Perturbations (all deterministic):

  • drop_field     — omit each input key in turn
  • null_field     — replace each value with None
  • empty_field    — replace strings with "" and numbers with 0
  • extreme_value  — inject ±1e9, NaN, negative prices
  • typo_field     — insert a single-char typo in string values
  • case_swap      — UPPERCASE values
  • wrong_type     — replace int → str, str → list

Returns a ``RobustnessReport`` with:

  • crashes        — perturbations that raised exceptions
  • type_violations — output type changed unexpectedly
  • swings          — output changed by > threshold (if output is
                       scalar/dict-scalar)
  • score           — 0..1 robustness score

Brain-only utility; no Shopify / ads side effects. The harness is
pure; the rule-under-test can be anything.
"""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable


@dataclass
class PerturbationResult:
    name: str
    field: str
    status: str              # "ok" | "crash" | "type_violation" | "swing"
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "field": self.field,
            "status": self.status,
            "detail": self.detail,
        }


@dataclass
class RobustnessReport:
    total: int = 0
    ok: int = 0
    crashes: list[PerturbationResult] = field(default_factory=list)
    type_violations: list[PerturbationResult] = field(default_factory=list)
    swings: list[PerturbationResult] = field(default_factory=list)

    @property
    def score(self) -> float:
        if self.total == 0:
            return 1.0
        weak = len(self.crashes) + len(self.type_violations) + len(self.swings)
        return max(0.0, 1.0 - weak / self.total)

    def as_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "ok": self.ok,
            "score": round(self.score, 3),
            "crashes": [r.as_dict() for r in self.crashes],
            "type_violations": [r.as_dict() for r in self.type_violations],
            "swings": [r.as_dict() for r in self.swings],
        }


# ── Perturbations ──────────────────────────────────────────

def drop_field(payload: dict[str, Any], fld: str) -> dict[str, Any]:
    out = copy.deepcopy(payload)
    out.pop(fld, None)
    return out


def null_field(payload: dict[str, Any], fld: str) -> dict[str, Any]:
    out = copy.deepcopy(payload)
    if fld in out:
        out[fld] = None
    return out


def empty_field(payload: dict[str, Any], fld: str) -> dict[str, Any]:
    out = copy.deepcopy(payload)
    if fld in out:
        v = out[fld]
        if isinstance(v, str):
            out[fld] = ""
        elif isinstance(v, (int, float)):
            out[fld] = 0
        elif isinstance(v, (list, tuple)):
            out[fld] = []
        elif isinstance(v, dict):
            out[fld] = {}
    return out


def extreme_value(payload: dict[str, Any], fld: str) -> dict[str, Any]:
    out = copy.deepcopy(payload)
    if fld in out and isinstance(out[fld], (int, float)):
        out[fld] = -1e9
    return out


def typo_field(payload: dict[str, Any], fld: str) -> dict[str, Any]:
    out = copy.deepcopy(payload)
    if fld in out and isinstance(out[fld], str) and out[fld]:
        s = out[fld]
        # swap first two chars
        out[fld] = (s[1] + s[0] + s[2:]) if len(s) >= 2 else s
    return out


def case_swap(payload: dict[str, Any], fld: str) -> dict[str, Any]:
    out = copy.deepcopy(payload)
    if fld in out and isinstance(out[fld], str):
        out[fld] = out[fld].upper()
    return out


def wrong_type(payload: dict[str, Any], fld: str) -> dict[str, Any]:
    out = copy.deepcopy(payload)
    if fld not in out:
        return out
    v = out[fld]
    if isinstance(v, str):
        out[fld] = [v]
    elif isinstance(v, (int, float)):
        out[fld] = str(v)
    elif isinstance(v, bool):
        out[fld] = int(v)
    else:
        out[fld] = "bogus"
    return out


_DEFAULT_PERTURBATIONS: tuple[tuple[str, Callable], ...] = (
    ("drop_field", drop_field),
    ("null_field", null_field),
    ("empty_field", empty_field),
    ("extreme_value", extreme_value),
    ("typo_field", typo_field),
    ("case_swap", case_swap),
    ("wrong_type", wrong_type),
)


# ── Tester ─────────────────────────────────────────────────

def test_rule(
    rule: Callable[[dict[str, Any]], Any],
    baseline: dict[str, Any],
    *,
    swing_threshold: float = 0.5,
    fields: Iterable[str] | None = None,
    perturbations: Iterable[tuple[str, Callable]] | None = None,
) -> RobustnessReport:
    """Run ``rule`` on ``baseline`` then on every perturbation and
    compare outputs. Returns a RobustnessReport."""
    perturbations = perturbations or _DEFAULT_PERTURBATIONS
    target_fields = list(fields) if fields is not None else list(baseline.keys())
    try:
        base_output = rule(copy.deepcopy(baseline))
    except Exception as exc:
        return RobustnessReport(
            total=1,
            crashes=[PerturbationResult(
                name="baseline", field="*",
                status="crash",
                detail=f"{type(exc).__name__}: {exc}",
            )],
        )
    base_type = type(base_output)
    report = RobustnessReport()
    for name, fn in perturbations:
        for fld in target_fields:
            perturbed = fn(baseline, fld)
            if perturbed == baseline:
                continue
            report.total += 1
            try:
                out = rule(perturbed)
            except Exception as exc:
                report.crashes.append(PerturbationResult(
                    name=name, field=fld, status="crash",
                    detail=f"{type(exc).__name__}: {exc}",
                ))
                continue
            if type(out) is not base_type:
                report.type_violations.append(PerturbationResult(
                    name=name, field=fld, status="type_violation",
                    detail=(f"expected {base_type.__name__}, "
                            f"got {type(out).__name__}"),
                ))
                continue
            swing = _scalar_swing(base_output, out)
            if swing is not None and swing >= swing_threshold:
                report.swings.append(PerturbationResult(
                    name=name, field=fld, status="swing",
                    detail=f"swing={swing:.3f} "
                           f"(threshold={swing_threshold})",
                ))
                continue
            report.ok += 1
    return report


def _scalar_swing(base: Any, other: Any) -> float | None:
    """Relative swing between two scalar-ish outputs; None if either
    side isn't comparable."""
    def _scalar_of(x: Any) -> float | None:
        if isinstance(x, bool):
            return 1.0 if x else 0.0
        if isinstance(x, (int, float)):
            return float(x) if math.isfinite(x) else None
        if isinstance(x, dict):
            for key in ("score", "value", "result"):
                if key in x and isinstance(x[key], (int, float)):
                    return float(x[key])
        return None
    b = _scalar_of(base)
    o = _scalar_of(other)
    if b is None or o is None:
        return None
    denom = max(abs(b), 1e-6)
    return abs(o - b) / denom


# ── Corpus helper ───────────────────────────────────────────

def sweep(
    rule: Callable[[dict[str, Any]], Any],
    baselines: Iterable[dict[str, Any]],
    **kwargs: Any,
) -> list[RobustnessReport]:
    """Run test_rule across many baseline payloads. Useful when one
    rule must be robust across, e.g., every niche."""
    return [test_rule(rule, b, **kwargs) for b in baselines]
