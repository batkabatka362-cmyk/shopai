"""Post-write verifier — read-back + drift detection.

Track 5 of AGI_HARDENING_PLAN. CLAUDE.md §4b/G paranoid-mode
requires: after a live write, read the resource back and verify
it matches expected. Sprint 1-3 have several write paths
(publisher_bundle, product_updater, campaign_activator) but no
consistent post-write check — silent drift (price rounding,
status regression, field truncation) slips through.

Surface — single generic function:

    report = verify_write(
        read_fn=lambda: api.get_product(pid),
        expected={"price": "29.99", "status": "active"},
        fields=("price", "status"),   # which keys to check
        tolerance={"price": 0.01},    # per-field fuzzy equality
    )
    if report.drift:
        emit outcome_event(kind="execution_drift", ...)

Design choices:

  * Caller provides the read_fn — no hard dependency on Shopify /
    Meta adapters, so it's trivially testable and reusable.
  * Tolerance map for float-ish fields (price, budget). Integer
    fields compare exact. String fields compare exact unless
    tolerance says "prefix" / "contains".
  * Timeout: caller is responsible for retries; the verifier
    makes a single attempt. The verifier catches exceptions from
    read_fn and surfaces them as drift with kind="read_failed".

Pure stdlib. Deterministic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from utils.logger import get_logger


logger = get_logger("execution.verify.post_write_verifier")


@dataclass
class VerifyConfig:
    fields: tuple[str, ...]
    tolerance: dict[str, Any] = field(default_factory=dict)
    allow_missing: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.fields:
            raise ValueError("fields required (non-empty)")


@dataclass
class DriftReport:
    drift: bool
    field_diffs: tuple[dict[str, Any], ...]
    read_ok: bool = True
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "drift": self.drift,
            "field_diffs": [
                dict(d) for d in self.field_diffs
            ],
            "read_ok": self.read_ok,
            "error": self.error,
        }


def _equal(
    expected: Any,
    actual: Any,
    *,
    tolerance: Any,
) -> bool:
    # Float tolerance
    if isinstance(tolerance, (int, float)) and tolerance > 0:
        try:
            return (
                abs(float(expected) - float(actual))
                <= float(tolerance)
            )
        except (TypeError, ValueError):
            return False
    # String modes
    if tolerance == "prefix":
        return str(actual or "").startswith(
            str(expected or ""),
        )
    if tolerance == "contains":
        return str(expected or "") in str(actual or "")
    if tolerance == "case_insensitive":
        return (
            str(expected or "").lower()
            == str(actual or "").lower()
        )
    # Default: exact equality after coercing to str when
    # types differ (Shopify often returns price as string
    # "29.99" even when we wrote float 29.99).
    if type(expected) is not type(actual):
        try:
            if isinstance(
                expected, (int, float),
            ) and isinstance(actual, str):
                return float(expected) == float(actual)
            if isinstance(
                expected, str,
            ) and isinstance(actual, (int, float)):
                return float(expected) == float(actual)
        except (TypeError, ValueError):
            pass
    return expected == actual


def _dig(
    resource: Any, field_path: str,
) -> tuple[bool, Any]:
    """Resolve a dotted field path on a dict or object.

    Returns (found, value). ``found=False`` when any segment
    along the path is missing.
    """
    cur: Any = resource
    for segment in field_path.split("."):
        if cur is None:
            return False, None
        if isinstance(cur, dict):
            if segment not in cur:
                return False, None
            cur = cur[segment]
        else:
            if not hasattr(cur, segment):
                return False, None
            cur = getattr(cur, segment)
    return True, cur


def verify_write(
    *,
    read_fn: Callable[[], Any],
    expected: dict[str, Any],
    config: VerifyConfig | None = None,
    fields: Iterable[str] | None = None,
    tolerance: dict[str, Any] | None = None,
    allow_missing: Iterable[str] | None = None,
) -> DriftReport:
    """Run a read-back and emit a DriftReport.

    Either pass ``config=VerifyConfig(...)`` or the individual
    ``fields`` / ``tolerance`` / ``allow_missing`` kwargs.
    """
    if config is None:
        if fields is None:
            raise ValueError(
                "fields or config required",
            )
        config = VerifyConfig(
            fields=tuple(fields),
            tolerance=dict(tolerance or {}),
            allow_missing=tuple(allow_missing or ()),
        )
    try:
        actual = read_fn()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "read_fn raised: %s", exc,
        )
        return DriftReport(
            drift=True,
            field_diffs=(),
            read_ok=False,
            error=f"read_fn failed: {exc}",
        )

    diffs: list[dict[str, Any]] = []
    for fname in config.fields:
        want = expected.get(fname)
        found, got = _dig(actual, fname)
        tol = config.tolerance.get(fname)
        if not found:
            if fname in config.allow_missing:
                continue
            diffs.append({
                "field": fname,
                "expected": want,
                "actual": None,
                "reason": "missing",
            })
            continue
        if not _equal(want, got, tolerance=tol):
            diffs.append({
                "field": fname,
                "expected": want,
                "actual": got,
                "reason": "mismatch",
            })
    drift = bool(diffs)
    return DriftReport(
        drift=drift,
        field_diffs=tuple(diffs),
        read_ok=True,
    )
