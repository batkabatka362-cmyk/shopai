"""Commitment verifier — cross-check promised outcome vs observed.

commitment_register stores promises the brain made. But when a
promise is marked "fulfilled", who actually verifies the outcome?
Today: nobody. That lets the system confuse itself into believing
it delivered when the KPI didn't move.

The verifier audits a commitment:

  1. Owner registers promises with a ``measurable_claim`` — e.g.
     "ROAS ≥ 1.5 over 3 days after ad launch".
  2. At fulfillment time the verifier pulls the relevant KPI
     measurements from an injected measurement provider.
  3. Checks the claim against the observations.
  4. Emits a ``VerificationVerdict``: *verified*, *unfulfilled*,
     *inconclusive*, or *unknown*.

Pure stdlib. Dependency-injected measurement lookup so tests don't
need live data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Literal

from utils.logger import get_logger


logger = get_logger("brain.commitment_verifier")


Verdict = Literal["verified", "unfulfilled", "inconclusive", "unknown"]
Operator = Literal["ge", "le", "gt", "lt", "eq", "ne"]


@dataclass
class MeasurableClaim:
    kpi: str
    operator: Operator
    threshold: float
    window_s: float = 86_400.0

    def __post_init__(self) -> None:
        if not self.kpi:
            raise ValueError("kpi required")
        if self.operator not in (
            "ge", "le", "gt", "lt", "eq", "ne",
        ):
            raise ValueError("invalid operator")
        if self.window_s <= 0:
            raise ValueError("window_s must be positive")

    def satisfied(self, observed: float) -> bool:
        if self.operator == "ge":
            return observed >= self.threshold
        if self.operator == "le":
            return observed <= self.threshold
        if self.operator == "gt":
            return observed > self.threshold
        if self.operator == "lt":
            return observed < self.threshold
        if self.operator == "eq":
            return observed == self.threshold
        return observed != self.threshold

    def as_dict(self) -> dict[str, Any]:
        return {
            "kpi": self.kpi,
            "operator": self.operator,
            "threshold": round(self.threshold, 4),
            "window_s": round(self.window_s, 2),
        }


@dataclass
class VerificationVerdict:
    commitment_id: str
    verdict: Verdict
    claim: MeasurableClaim | None
    observed_value: float | None
    observed_samples: int
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "commitment_id": self.commitment_id,
            "verdict": self.verdict,
            "claim": self.claim.as_dict() if self.claim else None,
            "observed_value": (
                round(self.observed_value, 4)
                if self.observed_value is not None else None
            ),
            "observed_samples": self.observed_samples,
            "note": self.note,
        }


# measurement_fn signature:
#   (kpi: str, from_ts: float, to_ts: float) -> list[float]
MeasurementFn = Callable[[str, float, float], Iterable[float]]


class CommitmentVerifier:
    def __init__(
        self,
        *,
        measurement_fn: MeasurementFn | None = None,
        min_samples: int = 1,
    ) -> None:
        if min_samples < 1:
            raise ValueError("min_samples must be ≥ 1")
        self._measurement_fn = measurement_fn
        self._min_samples = int(min_samples)
        # commitment_id → (claim, fulfillment_ts)
        self._claims: dict[str, tuple[MeasurableClaim, float]] = {}

    # ── Registration ─────────────────────────────────────

    def register_claim(
        self,
        commitment_id: str,
        claim: MeasurableClaim,
        *,
        fulfillment_ts: float,
    ) -> None:
        if not commitment_id:
            raise ValueError("commitment_id required")
        if fulfillment_ts <= 0:
            raise ValueError("fulfillment_ts must be positive")
        self._claims[commitment_id] = (claim, float(fulfillment_ts))

    def unregister_claim(self, commitment_id: str) -> bool:
        return self._claims.pop(commitment_id, None) is not None

    def claim_for(self, commitment_id: str) -> MeasurableClaim | None:
        entry = self._claims.get(commitment_id)
        return entry[0] if entry else None

    # ── Verify ───────────────────────────────────────────

    def _fetch(
        self, kpi: str, from_ts: float, to_ts: float,
    ) -> list[float]:
        if self._measurement_fn is None:
            return []
        try:
            samples = list(self._measurement_fn(kpi, from_ts, to_ts))
        except Exception as exc:
            logger.debug(
                "measurement_fn raised for %s: %s", kpi, exc,
            )
            return []
        return [float(s) for s in samples]

    def verify(
        self,
        commitment_id: str,
    ) -> VerificationVerdict:
        entry = self._claims.get(commitment_id)
        if entry is None:
            return VerificationVerdict(
                commitment_id=commitment_id,
                verdict="unknown",
                claim=None,
                observed_value=None,
                observed_samples=0,
                note="no claim registered",
            )
        claim, fulfilled_at = entry
        from_ts = fulfilled_at
        to_ts = fulfilled_at + claim.window_s
        samples = self._fetch(claim.kpi, from_ts, to_ts)
        if not samples:
            return VerificationVerdict(
                commitment_id=commitment_id,
                verdict="inconclusive",
                claim=claim,
                observed_value=None,
                observed_samples=0,
                note="no measurements in window",
            )
        if len(samples) < self._min_samples:
            return VerificationVerdict(
                commitment_id=commitment_id,
                verdict="inconclusive",
                claim=claim,
                observed_value=sum(samples) / len(samples),
                observed_samples=len(samples),
                note=(
                    f"only {len(samples)} samples "
                    f"(need ≥ {self._min_samples})"
                ),
            )
        mean = sum(samples) / len(samples)
        satisfied = claim.satisfied(mean)
        return VerificationVerdict(
            commitment_id=commitment_id,
            verdict="verified" if satisfied else "unfulfilled",
            claim=claim,
            observed_value=mean,
            observed_samples=len(samples),
            note=(
                "claim satisfied"
                if satisfied
                else f"observed {mean:.4f} failed {claim.operator} "
                     f"{claim.threshold:.4f}"
            ),
        )

    def verify_all(self) -> list[VerificationVerdict]:
        return [
            self.verify(cid) for cid in list(self._claims.keys())
        ]

    # ── Stats ────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        return {
            "registered_claims": len(self._claims),
            "min_samples": self._min_samples,
        }
