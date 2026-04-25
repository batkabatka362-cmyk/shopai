"""Fraud detector — score incoming orders for suspicious signals.

Every fraudulent order costs twice: the chargeback fee plus the
refunded COGS. Pattern signals stack quickly — high-value first
order + rush shipping + billing-shipping mismatch + new IP. A
rule-based scorer catches ~80% of obvious fraud with zero LLM
cost, flagging the rest for human review.

FraudDetector computes a 0-100 risk score by summing weighted
signal contributions. Signals ship with sensible defaults; the
registry is extensible.

Signals:

  • high_value_first_order   — first order > $500
  • mismatch_billing_shipping — countries differ
  • rush_shipping            — expedited on low-margin item
  • new_account              — < 2 days old at checkout
  • multiple_declines        — 2+ prior declines in 24h
  • email_disposable         — known throwaway domain
  • ip_vpn                    — caller-supplied flag
  • velocity_spike           — 3+ orders from same IP in 1h
  • address_lookup_fail      — postal code doesn't geocode

APIs:

  score(order) → FraudReport(score, signals_hit[], verdict)
  verdict(score) → allow / review / block
  register_signal(name, weight, evaluator)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Literal


Verdict = Literal["allow", "review", "block"]


@dataclass
class SignalHit:
    name: str
    weight: float
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "weight": round(self.weight, 2),
            "detail": self.detail,
        }


@dataclass
class FraudReport:
    order_id: str
    score: float
    verdict: Verdict
    signals_hit: list[SignalHit] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "score": round(self.score, 2),
            "verdict": self.verdict,
            "signals_hit": [h.as_dict() for h in self.signals_hit],
        }


SignalFn = Callable[[dict[str, Any]], tuple[bool, str]]


@dataclass
class Signal:
    name: str
    weight: float
    evaluator: SignalFn


# ── Built-in signals ────────────────────────────────────────

_DISPOSABLE_DOMAINS = {
    "mailinator.com", "guerrillamail.com", "trashmail.com",
    "10minutemail.com", "tempmail.com", "throwaway.email",
}


def _high_value_first_order(o: dict) -> tuple[bool, str]:
    if o.get("customer_order_count", 0) > 1:
        return False, ""
    val = float(o.get("order_value", 0) or 0)
    if val > 500:
        return True, f"first order value ${val:.2f}"
    return False, ""


def _billing_shipping_mismatch(o: dict) -> tuple[bool, str]:
    b = str(o.get("billing_country", "")).strip().lower()
    s = str(o.get("shipping_country", "")).strip().lower()
    if b and s and b != s:
        return True, f"billing={b} shipping={s}"
    return False, ""


def _rush_shipping(o: dict) -> tuple[bool, str]:
    if not o.get("rush_shipping"):
        return False, ""
    margin = float(o.get("margin_pct", 0.5) or 0.5)
    if margin < 0.2:
        return True, f"rush on margin {margin:.0%}"
    return False, ""


def _new_account(o: dict) -> tuple[bool, str]:
    days = float(o.get("account_age_days", 999) or 999)
    if days < 2:
        return True, f"{days}d old"
    return False, ""


def _multiple_declines(o: dict) -> tuple[bool, str]:
    n = int(o.get("declines_24h", 0) or 0)
    if n >= 2:
        return True, f"{n} declines in 24h"
    return False, ""


_EMAIL_DOMAIN_RE = re.compile(r"@([A-Za-z0-9.-]+)$")


def _email_disposable(o: dict) -> tuple[bool, str]:
    email = str(o.get("email", ""))
    m = _EMAIL_DOMAIN_RE.search(email)
    if not m:
        return False, ""
    domain = m.group(1).lower()
    if domain in _DISPOSABLE_DOMAINS:
        return True, f"disposable {domain}"
    return False, ""


def _ip_vpn(o: dict) -> tuple[bool, str]:
    if o.get("ip_vpn"):
        return True, "VPN/proxy flag set"
    return False, ""


def _velocity_spike(o: dict) -> tuple[bool, str]:
    n = int(o.get("orders_same_ip_1h", 0) or 0)
    if n >= 3:
        return True, f"{n} orders same IP / 1h"
    return False, ""


def _address_lookup_fail(o: dict) -> tuple[bool, str]:
    if o.get("address_lookup_failed"):
        return True, "postal geocode failed"
    return False, ""


_DEFAULT_SIGNALS: tuple[Signal, ...] = (
    Signal("high_value_first_order", 25.0, _high_value_first_order),
    Signal("mismatch_billing_shipping", 20.0,
            _billing_shipping_mismatch),
    Signal("rush_shipping", 10.0, _rush_shipping),
    Signal("new_account", 15.0, _new_account),
    Signal("multiple_declines", 30.0, _multiple_declines),
    Signal("email_disposable", 25.0, _email_disposable),
    Signal("ip_vpn", 15.0, _ip_vpn),
    Signal("velocity_spike", 30.0, _velocity_spike),
    Signal("address_lookup_fail", 20.0, _address_lookup_fail),
)


# ── Detector ────────────────────────────────────────────────

class FraudDetector:
    def __init__(self) -> None:
        self._signals: list[Signal] = list(_DEFAULT_SIGNALS)

    def register_signal(
        self, name: str, weight: float, evaluator: SignalFn,
    ) -> None:
        name = name.strip()
        if not name:
            raise ValueError("signal name required")
        # Replace existing by name
        self._signals = [
            s for s in self._signals if s.name != name
        ] + [Signal(name=name, weight=float(weight),
                     evaluator=evaluator)]

    def deregister(self, name: str) -> bool:
        before = len(self._signals)
        self._signals = [s for s in self._signals if s.name != name]
        return len(self._signals) < before

    def signals(self) -> list[str]:
        return [s.name for s in self._signals]

    # ── Scoring ────────────────────────────────────────────

    def score(self, order: dict[str, Any]) -> FraudReport:
        order_id = str(order.get("order_id",
                                   order.get("id", "")))
        hits: list[SignalHit] = []
        total = 0.0
        for signal in self._signals:
            try:
                fired, detail = signal.evaluator(order)
            except Exception:
                continue
            if fired:
                total += signal.weight
                hits.append(SignalHit(
                    name=signal.name,
                    weight=signal.weight,
                    detail=detail,
                ))
        total = min(100.0, total)
        return FraudReport(
            order_id=order_id,
            score=total,
            verdict=self.verdict(total),
            signals_hit=hits,
        )

    @staticmethod
    def verdict(score: float) -> Verdict:
        if score >= 60:
            return "block"
        if score >= 30:
            return "review"
        return "allow"

    # ── Batch ──────────────────────────────────────────────

    def batch(
        self, orders: Iterable[dict[str, Any]],
    ) -> list[FraudReport]:
        reports = [self.score(o) for o in orders]
        reports.sort(key=lambda r: -r.score)
        return reports
