"""Customer support chatbot (lite) — LX.1 first-line responder.

Sprint 3 S3-7 (P2, LX.1 in docs/AGI_STACK.md). Rule-based FAQ +
refund + shipping + order-status matcher. LLM-free first pass so
the system can answer simple questions before the owner is paying
for LLM credits per ticket. Escalation path hands unanswerable
questions back to the owner via the Telegram adapter.

Design principles:
  * Deterministic — same question + same rules → same answer.
  * Offline — pure stdlib, no network call.
  * Observable — every match returns which rule fired, so the
    brain can learn which patterns never match and surface gaps.
  * Extensible — owner can ``add_rule()`` at runtime; defaults
    cover the top-12 dropshipping support questions.

When no rule matches with enough confidence, verdict=escalate so
``agents/owner_dialog/notify.notify_owner`` (or similar) can push
the ticket to Telegram.

Pairs with S3-2 legal templates (terms + returns + shipping) —
when the rule is a "quote the policy" answer, the body is filled
from the rendered policy page.
"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from typing import Any, Iterable


_DEFAULT_ESCALATE_CONFIDENCE = 0.30


@dataclass
class SupportRule:
    """A single FAQ matching rule."""
    rule_id: str
    pattern: str              # regex, case-insensitive
    answer: str
    kind: str = "faq"
    weight: float = 1.0

    def compiled(self) -> Any:
        return re.compile(self.pattern, re.IGNORECASE)

    def as_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "pattern": self.pattern,
            "answer": self.answer,
            "kind": self.kind,
            "weight": self.weight,
        }


@dataclass
class SupportAnswer:
    """Result of a support query."""
    verdict: str              # "answered" | "escalate"
    kind: str = "faq"
    text: str = ""
    confidence: float = 0.0
    matched_rules: tuple[str, ...] = ()
    escalate_reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "kind": self.kind,
            "text": self.text,
            "confidence": round(self.confidence, 4),
            "matched_rules": list(self.matched_rules),
            "escalate_reason": self.escalate_reason,
        }


# ── Default rule set ────────────────────────────────────────

_DEFAULT_RULES: tuple[SupportRule, ...] = (
    SupportRule(
        rule_id="shipping_time",
        pattern=r"\b(how long|shipping time|when will|delivery time|arrive)\b",
        answer=(
            "Standard delivery takes 7-15 business days. "
            "You'll receive a tracking number by email once "
            "your order ships."
        ),
        kind="shipping",
    ),
    SupportRule(
        rule_id="shipping_cost",
        pattern=r"\b(shipping cost|shipping fee|cost to ship|free shipping)\b",
        answer=(
            "Shipping cost is calculated at checkout based "
            "on destination and order weight. Some items "
            "qualify for free shipping."
        ),
        kind="shipping",
    ),
    SupportRule(
        rule_id="where_is_my_order",
        pattern=r"\b(where.*order|order status|track(ing)?|hasn'?t arrived|haven'?t received)\b",
        answer=(
            "Please share your order number and we'll look "
            "it up for you. You can also track via the link "
            "in your shipping confirmation email."
        ),
        kind="order_status",
    ),
    SupportRule(
        rule_id="refund_request",
        pattern=r"\b(refund|money back|return my money)\b",
        answer=(
            "Yes — we offer refunds on returned items. See "
            "our Return + Refund Policy for the return "
            "window and how to start a return. Refunds are "
            "issued to the original payment method within 7 "
            "business days of receipt."
        ),
        kind="refund",
        weight=1.2,
    ),
    SupportRule(
        rule_id="return_how",
        pattern=r"\b(how.*return|return (an item|the product|my order)|exchange)\b",
        answer=(
            "To start a return, email us with your order "
            "number and the reason for return. We'll reply "
            "with return instructions within 1 business day."
        ),
        kind="refund",
    ),
    SupportRule(
        rule_id="damaged_defective",
        pattern=r"\b(damaged|defective|broken|wrong item|not as described)\b",
        answer=(
            "Sorry about that! If the item arrived damaged "
            "or defective we cover return shipping and offer "
            "a full refund or replacement. Please share "
            "photos and your order number."
        ),
        kind="refund",
        weight=1.3,
    ),
    SupportRule(
        rule_id="cancel_order",
        pattern=r"\b(cancel.*order|cancel my order|stop the order)\b",
        answer=(
            "Orders can be cancelled before they ship. "
            "Please reply with your order number and we'll "
            "try to cancel it. If the order has already "
            "shipped we'll process it as a return once it "
            "arrives."
        ),
        kind="order_status",
    ),
    SupportRule(
        rule_id="change_address",
        pattern=r"\b(change.*address|wrong address|update.*address|shipping address)\b",
        answer=(
            "If your order hasn't shipped yet we can update "
            "the address — please reply with your order "
            "number and the correct address."
        ),
        kind="order_status",
    ),
    SupportRule(
        rule_id="payment_methods",
        pattern=r"\b(payment method|do you accept|pay with|credit card|paypal)\b",
        answer=(
            "We accept major credit cards, PayPal, and "
            "Apple/Google Pay at checkout."
        ),
        kind="faq",
    ),
    SupportRule(
        rule_id="contact",
        pattern=r"\b(contact|speak to (a )?(person|human|agent)|call|phone|customer service)\b",
        answer=(
            "You can reach us by replying to any order "
            "email or via the contact form on our site. "
            "We answer within 1 business day."
        ),
        kind="faq",
    ),
    SupportRule(
        rule_id="international",
        pattern=r"\b(international|outside (the )?us|outside (the )?(uk|eu)|ship to|deliver to)\b",
        answer=(
            "We currently ship to the US, EU, and UK. "
            "Contact us if you need shipping to another "
            "region — we may be able to arrange it."
        ),
        kind="shipping",
    ),
    SupportRule(
        rule_id="customs_duties",
        pattern=r"\b(customs|duties|import tax|vat)\b",
        answer=(
            "For international orders, customers are "
            "responsible for any customs fees, import "
            "duties, or taxes imposed by their country."
        ),
        kind="shipping",
    ),
)


class SupportChatbot:
    """Rule-based support first-line responder."""

    def __init__(
        self,
        rules: Iterable[SupportRule] | None = None,
        *,
        escalate_confidence_floor: float = (
            _DEFAULT_ESCALATE_CONFIDENCE
        ),
    ) -> None:
        if not 0.0 <= escalate_confidence_floor <= 1.0:
            raise ValueError(
                "escalate_confidence_floor must be in [0, 1]",
            )
        self._lock = threading.Lock()
        self._floor = float(escalate_confidence_floor)
        self._rules: dict[str, SupportRule] = {}
        for r in (
            rules if rules is not None else _DEFAULT_RULES
        ):
            self._rules[r.rule_id] = r

    # ── Rule management ─────────────────────────────────

    def add_rule(self, rule: SupportRule) -> None:
        if not rule.rule_id:
            raise ValueError("rule.rule_id required")
        try:
            rule.compiled()
        except re.error as exc:
            raise ValueError(
                f"rule {rule.rule_id!r} has invalid regex: "
                f"{exc}",
            ) from exc
        with self._lock:
            self._rules[rule.rule_id] = rule

    def remove_rule(self, rule_id: str) -> bool:
        with self._lock:
            return self._rules.pop(rule_id, None) is not None

    def rules(self) -> list[SupportRule]:
        with self._lock:
            return list(self._rules.values())

    # ── Answering ────────────────────────────────────────

    def answer(
        self, question: str,
    ) -> SupportAnswer:
        text = (question or "").strip()
        if not text:
            return SupportAnswer(
                verdict="escalate",
                kind="empty",
                confidence=0.0,
                escalate_reason="empty question",
            )
        matches: list[tuple[SupportRule, int]] = []
        with self._lock:
            rules = list(self._rules.values())
        for rule in rules:
            try:
                pattern = rule.compiled()
            except re.error:
                continue
            if pattern.search(text):
                match_count = len(
                    pattern.findall(text),
                )
                matches.append((rule, match_count))
        if not matches:
            return SupportAnswer(
                verdict="escalate",
                kind="unmatched",
                confidence=0.0,
                escalate_reason="no matching rule",
            )
        matches.sort(
            key=lambda mr: (
                -(mr[0].weight * mr[1]),
                mr[0].rule_id,
            ),
        )
        # Confidence ∝ best-rule weight × match count / total
        # match-weighted score over all rules.
        best_rule, best_count = matches[0]
        total_weighted = sum(
            r.weight * n for r, n in matches
        )
        best_weighted = best_rule.weight * best_count
        confidence = (
            (best_weighted / total_weighted)
            if total_weighted > 0
            else 0.0
        )
        # Escalate if even the top rule is weak
        if (
            best_weighted < 1.0
            or confidence < self._floor
        ):
            return SupportAnswer(
                verdict="escalate",
                kind=best_rule.kind,
                text=best_rule.answer,
                confidence=confidence,
                matched_rules=tuple(
                    r.rule_id for r, _ in matches
                ),
                escalate_reason=(
                    f"confidence {confidence:.2f} < floor "
                    f"{self._floor:.2f}"
                ),
            )
        return SupportAnswer(
            verdict="answered",
            kind=best_rule.kind,
            text=best_rule.answer,
            confidence=confidence,
            matched_rules=tuple(
                r.rule_id for r, _ in matches
            ),
        )

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "rules": sorted(self._rules.keys()),
                "rule_count": len(self._rules),
                "escalate_confidence_floor": self._floor,
            }
