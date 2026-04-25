"""Invariant monitor — continuous checks that the system is still sane.

Bugs that matter in production don't throw exceptions — they silently
drift invariants. A discount strategy that creates negative unit
margin. A sync that leaves inventory below zero. A refund pipeline
that outputs a row where ``refunded > ordered``. The invariant monitor
formalises these as named predicates the daemon re-evaluates every
cycle, captures per-invariant breach counts + trends, and raises
alerts when a breach pattern repeats.

API:

    mon = InvariantMonitor()
    mon.register(Invariant(
        name="inventory_non_negative",
        predicate=lambda snap: all(
            p.get("on_hand", 0) >= 0 for p in snap["products"]
        ),
        severity="critical",
        message="on_hand went negative on at least one SKU",
    ))

    report = mon.check(snap)                    # single tick
    mon.resolve("inventory_non_negative")       # flag as fixed

Each invariant persists its own breach streak + total; an alert fires
when the streak crosses the alert threshold (default 3 repeats).

Pure stdlib, in-memory (persist the interesting events via the
experience recorder if desired).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Literal


Severity = Literal["info", "warning", "critical"]


@dataclass
class Invariant:
    name: str
    predicate: Callable[[Any], bool]   # True ⇒ invariant holds
    severity: Severity = "warning"
    message: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Invariant.name required")
        if self.severity not in ("info", "warning", "critical"):
            raise ValueError("severity must be info|warning|critical")

    def holds(self, snapshot: Any) -> bool:
        try:
            return bool(self.predicate(snapshot))
        except Exception:
            # Fail closed — if the predicate crashes the invariant is
            # considered breached so the issue surfaces.
            return False


@dataclass
class Breach:
    invariant: str
    severity: Severity
    message: str
    streak: int
    total: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "invariant": self.invariant,
            "severity": self.severity,
            "message": self.message,
            "streak": self.streak,
            "total": self.total,
        }


@dataclass
class MonitorReport:
    checked: int
    breaches: list[Breach] = field(default_factory=list)
    alerts: list[Breach] = field(default_factory=list)
    ts: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "checked": self.checked,
            "breaches": [b.as_dict() for b in self.breaches],
            "alerts": [a.as_dict() for a in self.alerts],
            "ts": self.ts,
        }


class InvariantMonitor:
    def __init__(self, *, alert_after: int = 3) -> None:
        if alert_after < 1:
            raise ValueError("alert_after must be ≥ 1")
        self._alert_after = int(alert_after)
        self._invariants: dict[str, Invariant] = {}
        self._streak: dict[str, int] = {}
        self._total: dict[str, int] = {}
        self._last_resolved: dict[str, float] = {}

    # ── Registration ─────────────────────────────────────

    def register(
        self, inv: Invariant, overwrite: bool = False,
    ) -> None:
        if inv.name in self._invariants and not overwrite:
            raise ValueError(
                f"invariant {inv.name!r} already registered",
            )
        self._invariants[inv.name] = inv
        self._streak.setdefault(inv.name, 0)
        self._total.setdefault(inv.name, 0)

    def unregister(self, name: str) -> bool:
        popped = self._invariants.pop(name, None)
        self._streak.pop(name, None)
        self._total.pop(name, None)
        self._last_resolved.pop(name, None)
        return popped is not None

    def invariants(self) -> list[Invariant]:
        return list(self._invariants.values())

    def resolve(self, name: str) -> bool:
        if name not in self._invariants:
            return False
        self._streak[name] = 0
        self._last_resolved[name] = time.time()
        return True

    # ── Checks ───────────────────────────────────────────

    def check(self, snapshot: Any) -> MonitorReport:
        report = MonitorReport(
            checked=len(self._invariants), ts=time.time(),
        )
        for inv in self._invariants.values():
            if inv.holds(snapshot):
                # Clear streak as soon as it holds again.
                self._streak[inv.name] = 0
                continue
            self._streak[inv.name] = self._streak.get(inv.name, 0) + 1
            self._total[inv.name] = self._total.get(inv.name, 0) + 1
            breach = Breach(
                invariant=inv.name,
                severity=inv.severity,
                message=inv.message,
                streak=self._streak[inv.name],
                total=self._total[inv.name],
            )
            report.breaches.append(breach)
            if self._streak[inv.name] >= self._alert_after:
                report.alerts.append(breach)
        return report

    # ── Stats ────────────────────────────────────────────

    def streak(self, name: str) -> int:
        return self._streak.get(name, 0)

    def total(self, name: str) -> int:
        return self._total.get(name, 0)

    def stats(self) -> dict[str, Any]:
        return {
            "invariants": len(self._invariants),
            "active_breaches": sum(
                1 for name in self._invariants
                if self._streak.get(name, 0) > 0
            ),
            "by_name": {
                name: {
                    "streak": self._streak.get(name, 0),
                    "total": self._total.get(name, 0),
                    "last_resolved": self._last_resolved.get(name),
                }
                for name in self._invariants
            },
        }


# ── Canonical invariants ─────────────────────────────────

def inventory_non_negative(
    products_key: str = "products",
    on_hand_key: str = "on_hand",
) -> Invariant:
    def _check(snap: Any) -> bool:
        products = (snap or {}).get(products_key) or []
        return all(
            int(p.get(on_hand_key, 0)) >= 0 for p in products
        )
    return Invariant(
        name="inventory_non_negative",
        predicate=_check,
        severity="critical",
        message="on_hand < 0 on at least one SKU",
    )


def refunds_le_orders(
    orders_key: str = "orders",
    refunds_key: str = "refunds",
) -> Invariant:
    def _check(snap: Any) -> bool:
        snap = snap or {}
        total_orders = sum(
            float(o.get("amount", 0.0))
            for o in snap.get(orders_key, [])
        )
        total_refunds = sum(
            float(r.get("amount", 0.0))
            for r in snap.get(refunds_key, [])
        )
        return total_refunds <= total_orders + 1e-6
    return Invariant(
        name="refunds_le_orders",
        predicate=_check,
        severity="critical",
        message="refund total exceeded order total — check sync",
    )


def positive_margin(
    products_key: str = "products",
    margin_key: str = "margin",
) -> Invariant:
    def _check(snap: Any) -> bool:
        products = (snap or {}).get(products_key) or []
        return all(
            float(p.get(margin_key, 0.0)) > 0.0
            for p in products if margin_key in p
        )
    return Invariant(
        name="positive_margin",
        predicate=_check,
        severity="warning",
        message="at least one product has non-positive margin",
    )
