"""Ethics gate — hard-constraint checker over outgoing actions.

An autonomous brain that optimises only for revenue will eventually
cross lines: spammy emails, deceptive discount framing, negative-
option pricing, misleading product claims, over-aggressive
competitor scraping. The brain may not notice it's doing harm —
constraints that aren't encoded are effectively absent.

EthicsGate runs every outbound action through a battery of
deterministic rules. Each rule inspects a draft action dict and
returns ``None`` if fine or ``Violation`` with severity and reason
if not. The gate's decision:

  • All clear           → ``status="allowed"``
  • Any soft violation  → ``status="soft_block"`` (owner approves)
  • Any hard violation  → ``status="hard_block"``

Rules (zero LLM, pure Python):

  • no_deceptive_price_anchor — "Was $9999, now $29" when the
    anchor never existed at that price.
  • no_scarcity_lie — "Only 3 left" when inventory > 3.
  • no_spam_frequency — more than 2 emails/24h to the same contact.
  • no_fake_reviews — product has ``fake=True`` in content.
  • no_forbidden_categories — e.g. "weapons", "prescription_drugs".
  • no_pii_leak — email/phone pattern in an outbound public message.
  • no_deceptive_urgency — "24h only!" when the sale runs for 14d.
  • owner_spending_cap — spend above the owner-set daily cap is
    hard-blocked.

All violations are persisted as ``category=ethics_violation
score=4.8`` memory events so the owner can review and the brain
learns patterns. The gate is intentionally conservative: false
positives cost owner friction, false negatives cost reputation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Literal


Severity = Literal["hard", "soft"]


@dataclass
class Violation:
    rule: str
    severity: Severity
    reason: str
    detail: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "severity": self.severity,
            "reason": self.reason,
            "detail": self.detail,
        }


@dataclass
class Verdict:
    status: Literal["allowed", "soft_block", "hard_block"]
    violations: list[Violation] = field(default_factory=list)

    @property
    def allowed(self) -> bool:
        return self.status == "allowed"

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "violations": [v.as_dict() for v in self.violations],
        }


# ── Rule implementations ────────────────────────────────────

_FORBIDDEN_CATEGORIES = {
    "weapons", "prescription_drugs", "controlled_substances",
    "hate_speech", "csam", "stolen_goods",
}

_PII_EMAIL = re.compile(
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}",
)
_PII_PHONE = re.compile(
    r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}",
)


def no_deceptive_price_anchor(action: dict[str, Any]) -> Violation | None:
    if action.get("kind") != "set_price":
        return None
    was = action.get("compare_at_price")
    now = action.get("price")
    verified_max = action.get("verified_historical_max_price")
    if was and verified_max is not None and was > verified_max * 1.05:
        return Violation(
            rule="no_deceptive_price_anchor",
            severity="hard",
            reason=(f"compare_at_price {was} > historical max "
                    f"{verified_max} (+5% tolerance)"),
            detail={"was": was, "historical_max": verified_max,
                    "now": now},
        )
    return None


def no_scarcity_lie(action: dict[str, Any]) -> Violation | None:
    if action.get("kind") != "publish_scarcity":
        return None
    claimed = action.get("claimed_stock")
    actual = action.get("actual_stock")
    if claimed is None or actual is None:
        return None
    if claimed < actual:
        return Violation(
            rule="no_scarcity_lie",
            severity="hard",
            reason=f"claimed {claimed} < actual {actual}",
            detail={"claimed": claimed, "actual": actual},
        )
    return None


def no_spam_frequency(action: dict[str, Any]) -> Violation | None:
    if action.get("kind") != "send_email":
        return None
    recent_count = int(action.get("emails_in_last_24h", 0) or 0)
    if recent_count >= 2:
        return Violation(
            rule="no_spam_frequency",
            severity="soft",
            reason=f"{recent_count + 1} emails to same contact in 24h",
            detail={"recent_count": recent_count,
                    "recipient": action.get("recipient")},
        )
    return None


def no_fake_reviews(action: dict[str, Any]) -> Violation | None:
    if action.get("kind") != "publish_review":
        return None
    if action.get("fake") is True or action.get("source") == "generated":
        return Violation(
            rule="no_fake_reviews",
            severity="hard",
            reason="review flagged as fake or generated",
            detail={"product_id": action.get("product_id")},
        )
    return None


def no_forbidden_categories(action: dict[str, Any]) -> Violation | None:
    cat = str(action.get("category") or "").strip().lower()
    if cat in _FORBIDDEN_CATEGORIES:
        return Violation(
            rule="no_forbidden_categories",
            severity="hard",
            reason=f"category '{cat}' is forbidden",
            detail={"category": cat},
        )
    return None


def no_pii_leak(action: dict[str, Any]) -> Violation | None:
    audience = action.get("audience")
    if audience not in ("public", "social"):
        return None
    body = str(action.get("body") or "")
    if _PII_EMAIL.search(body) or _PII_PHONE.search(body):
        return Violation(
            rule="no_pii_leak",
            severity="hard",
            reason="outbound public message contains email/phone PII",
            detail={"sample": body[:80]},
        )
    return None


def no_deceptive_urgency(action: dict[str, Any]) -> Violation | None:
    if action.get("kind") != "publish_sale_copy":
        return None
    claim_hours = action.get("claim_hours")
    actual_hours = action.get("actual_duration_hours")
    if claim_hours is None or actual_hours is None:
        return None
    # If the copy claims the sale is half-or-less the actual duration.
    if claim_hours * 2 < actual_hours:
        return Violation(
            rule="no_deceptive_urgency",
            severity="soft",
            reason=(f"copy claims {claim_hours}h; sale actually runs "
                    f"{actual_hours}h"),
            detail={"claim_hours": claim_hours,
                    "actual_hours": actual_hours},
        )
    return None


def owner_spending_cap(action: dict[str, Any]) -> Violation | None:
    if action.get("kind") != "spend":
        return None
    amount = float(action.get("amount_usd", 0) or 0)
    already = float(action.get("already_spent_today_usd", 0) or 0)
    cap = float(action.get("daily_cap_usd", 0) or 0)
    if cap > 0 and (amount + already) > cap:
        return Violation(
            rule="owner_spending_cap",
            severity="hard",
            reason=(f"spend {amount} + already {already} exceeds "
                    f"daily cap {cap}"),
            detail={"amount": amount, "already": already, "cap": cap},
        )
    return None


_RULES: tuple[Callable[[dict[str, Any]], Violation | None], ...] = (
    no_deceptive_price_anchor,
    no_scarcity_lie,
    no_spam_frequency,
    no_fake_reviews,
    no_forbidden_categories,
    no_pii_leak,
    no_deceptive_urgency,
    owner_spending_cap,
)


# ── Gate ────────────────────────────────────────────────────

def check(action: dict[str, Any]) -> Verdict:
    """Run every rule and aggregate into a Verdict."""
    violations: list[Violation] = []
    for rule in _RULES:
        v = rule(action)
        if v is not None:
            violations.append(v)
    if not violations:
        return Verdict(status="allowed", violations=[])
    if any(v.severity == "hard" for v in violations):
        return Verdict(status="hard_block", violations=violations)
    return Verdict(status="soft_block", violations=violations)


def registered_rules() -> list[str]:
    return [r.__name__ for r in _RULES]
