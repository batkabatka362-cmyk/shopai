"""Match Shopify webhook events to engine actions and feed LearningLoop.

Audit #5 — Webhook Feedback Loop. The pre-fix system had three
of the four learning-loop edges wired (decision → memory,
decision → executor, executor → outcome score), but the **real
world** edge was missing: a Shopify order that actually used a
minted discount code never got tagged back to the engine that
minted it. The autonomous loop was scoring its own predictions,
not its own behaviour.

This bridge is the missing edge. Each event from
``ShopifyWebhookHandler`` is examined for a discount code (or
similar identifier) that ties back to an action in the approval
queue's ``EXECUTED`` set. When a match is found, ``LearningLoop``
gets a positive (orders/create) or negative (orders/cancelled,
refunds/create) signal tagged to the original engine. Orphan
events — orders without an engine-minted code — feed the loop as
a generic market-signal input so the system still benefits from
ambient revenue / churn data.

Best-effort throughout: every external call (queue lookup,
LearningLoop.learn, etc.) is wrapped so a misconfigured
sub-system doesn't break the webhook handler. The webhook itself
already happened; recording must not propagate failures.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("feedback.webhook_bridge")

_LOCK = threading.RLock()
_INSTANCE: "WebhookFeedbackBridge | None" = None


def _is_test_environment() -> bool:
    """Pattern J — LearningLoop.learn writes to brain memory +
    memory_intelligence + data_architecture, all of which back to
    on-disk SQLite. Tests that exercise this bridge without mocking
    the LearningLoop will pollute those stores. Defense-in-depth
    gate: short-circuit the learning fan-out under pytest. Tests
    that need to verify learning behaviour patch this to return
    False (same pattern as the writeback recorder and hooks
    dispatcher).
    """
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


# Topic → outcome polarity. Anything not listed is treated as a
# raw market signal (no positive/negative tilt; just feeds the
# loop with revenue / churn observation context).
_POSITIVE_TOPICS = {"orders/create", "orders/paid"}
_NEGATIVE_TOPICS = {"orders/cancelled", "refunds/create"}


class WebhookFeedbackBridge:
    """Bridge from Shopify webhook events to the LearningLoop."""

    def __init__(self) -> None:
        self._approval_queue = None
        self._learning_loop = None
        self._stats = {
            "events_seen": 0,
            "matched_actions": 0,
            "orphan_events": 0,
            "feedback_recorded": 0,
            "errors": 0,
        }

    # ── Public API ─────────────────────────────────────────────

    def handle_event(
        self,
        topic: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Handle a single webhook event.

        Returns a small audit dict — not consumed by the webhook
        handler itself (which already returned to Shopify long
        ago) but useful for tests and ops dashboards.
        """
        self._stats["events_seen"] += 1
        if not isinstance(topic, str) or not topic:
            return {"status": "noop", "reason": "missing_topic"}
        if not isinstance(payload, dict):
            payload = {}

        try:
            return self._handle_event_inner(topic, payload)
        except Exception as exc:  # noqa: BLE001
            logger.debug("webhook bridge raised on %s: %s", topic, exc)
            self._stats["errors"] += 1
            return {"status": "error", "error": str(exc)}

    def get_stats(self) -> dict[str, Any]:
        return dict(self._stats)

    # ── Internals ─────────────────────────────────────────────

    def _handle_event_inner(
        self, topic: str, payload: dict[str, Any],
    ) -> dict[str, Any]:
        polarity = self._polarity(topic)
        codes = _extract_discount_codes(payload)

        if codes:
            matched = self._match_to_action(codes)
            if matched is not None:
                self._stats["matched_actions"] += 1
                return self._feed_matched(
                    topic=topic,
                    polarity=polarity,
                    payload=payload,
                    action=matched,
                )

        # Orphan path — no code match. Still useful to feed the
        # loop with the raw event so future engines can correlate
        # revenue / churn with their own decisions.
        self._stats["orphan_events"] += 1
        return self._feed_orphan(
            topic=topic, polarity=polarity, payload=payload,
        )

    @staticmethod
    def _polarity(topic: str) -> str:
        if topic in _POSITIVE_TOPICS:
            return "positive"
        if topic in _NEGATIVE_TOPICS:
            return "negative"
        return "neutral"

    def _match_to_action(
        self, codes: list[str],
    ) -> dict[str, Any] | None:
        """Look up an EXECUTED action in the approval queue whose
        ``result.code`` matches any of the discount codes in the
        webhook payload.

        Returns the matching :class:`ApprovalAction` snapshot (as
        a dict) or ``None`` when nothing matches. The lookup is
        case-insensitive — Shopify uppercases discount codes on
        the storefront but engines often mint them in mixed case.
        """
        queue = self._get_approval_queue()
        if queue is None:
            return None

        try:
            snapshot = queue.list_executed(limit=500)
        except Exception as exc:  # noqa: BLE001
            logger.debug("approval queue lookup failed: %s", exc)
            return None

        wanted = {c.strip().lower() for c in codes if c}
        for action in snapshot:
            result = action.result or {}
            minted_code = str(result.get("code", "")).strip().lower()
            if minted_code and minted_code in wanted:
                return action.to_dict()
        return None

    def _feed_matched(
        self,
        *,
        topic: str,
        polarity: str,
        payload: dict[str, Any],
        action: dict[str, Any],
    ) -> dict[str, Any]:
        """Tagged-feedback path. The order/refund traces back to
        an engine action; LearningLoop sees a clean cause-effect
        signal."""
        engine = action.get("engine", "")
        action_type = action.get("action_type", "")

        metrics = _extract_metrics(topic, polarity, payload)
        result = {
            "topic": topic,
            "polarity": polarity,
            "shopify_event_at": payload.get("created_at"),
            "matched_action_id": action.get("id"),
            **metrics,
        }

        ok = self._learn(
            category=engine or "unknown",
            input_data={"action": action, "topic": topic},
            action=action_type or "webhook_outcome",
            result=result,
            metrics=metrics,
        )
        if ok:
            self._stats["feedback_recorded"] += 1
        return {
            "status": "matched",
            "engine": engine,
            "action_type": action_type,
            "polarity": polarity,
            "matched_action_id": action.get("id"),
            "feedback_recorded": ok,
        }

    def _feed_orphan(
        self,
        *,
        topic: str,
        polarity: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Untagged feedback path. The event isn't tied to any
        engine action; we still feed the loop with a generic
        market-signal entry so revenue / churn observations
        accumulate as ambient context."""
        metrics = _extract_metrics(topic, polarity, payload)
        result = {
            "topic": topic,
            "polarity": polarity,
            "shopify_event_at": payload.get("created_at"),
            **metrics,
        }
        ok = self._learn(
            category="market_signals",
            input_data={"topic": topic},
            action=topic,
            result=result,
            metrics=metrics,
        )
        if ok:
            self._stats["feedback_recorded"] += 1
        return {
            "status": "orphan",
            "polarity": polarity,
            "feedback_recorded": ok,
        }

    def _learn(
        self,
        *,
        category: str,
        input_data: dict[str, Any],
        action: str,
        result: dict[str, Any],
        metrics: dict[str, Any],
    ) -> bool:
        """Best-effort ``LearningLoop.learn`` call.

        Short-circuits under pytest (Pattern J) — LearningLoop.learn
        writes to multiple persistent SQLite stores, and a test
        firing this without mocking the loop would leave residue
        in the dev DBs. The bridge's tests (test_webhook_feedback_bridge)
        explicitly inject a MagicMock loop AND disable this gate so
        they can verify the learning fan-out shape; production
        callers (api/server.py webhook handler) run with the gate
        off because PYTEST_CURRENT_TEST isn't set.
        """
        if _is_test_environment():
            return False
        loop = self._get_learning_loop()
        if loop is None:
            return False
        try:
            loop.learn(
                category=category,
                input_data=input_data,
                action=action,
                result=result,
                metrics=metrics,
            )
            return True
        except Exception as exc:  # noqa: BLE001
            logger.debug("learning_loop.learn failed: %s", exc)
            self._stats["errors"] += 1
            return False

    # ── Lazy singletons ───────────────────────────────────────

    def _get_approval_queue(self) -> Any | None:
        if self._approval_queue is not None:
            return self._approval_queue
        try:
            from core.approval import get_approval_queue
            self._approval_queue = get_approval_queue()
        except Exception as exc:  # noqa: BLE001
            logger.debug("approval queue init failed: %s", exc)
            self._approval_queue = None
        return self._approval_queue

    def _get_learning_loop(self) -> Any | None:
        if self._learning_loop is not None:
            return self._learning_loop
        try:
            from core.brain.learning_loop import LearningLoop
            self._learning_loop = LearningLoop()
        except Exception as exc:  # noqa: BLE001
            logger.debug("learning_loop init failed: %s", exc)
            self._learning_loop = None
        return self._learning_loop


# ── Helpers ────────────────────────────────────────────────────


def _extract_discount_codes(payload: dict[str, Any]) -> list[str]:
    """Pull discount codes from a Shopify webhook payload.

    Shopify uses two fields: ``discount_codes`` (per-order array
    of ``{code, amount, type}``) and the legacy ``discount_code``
    (string, not nested). The bridge accepts both shapes.
    Refunds carry the codes only via the ``order`` sub-object.
    """
    codes: list[str] = []
    arr = payload.get("discount_codes")
    if isinstance(arr, list):
        for entry in arr:
            if isinstance(entry, dict):
                code = entry.get("code")
                if isinstance(code, str) and code.strip():
                    codes.append(code.strip())
            elif isinstance(entry, str) and entry.strip():
                codes.append(entry.strip())
    legacy = payload.get("discount_code")
    if isinstance(legacy, str) and legacy.strip():
        codes.append(legacy.strip())

    # Refund payloads nest the order as ``order``; descend if
    # present.
    nested = payload.get("order")
    if isinstance(nested, dict):
        codes.extend(_extract_discount_codes(nested))

    return codes


def _extract_metrics(
    topic: str, polarity: str, payload: dict[str, Any],
) -> dict[str, Any]:
    """Build metrics dict from the webhook payload.

    The LearningLoop's ``learn(... metrics=...)`` consumes:

      * ``profit`` — revenue change in ABSOLUTE dollars (positive
        for orders, negative for refunds).
      * ``conversion`` — 1.0 on order create, 0 on cancel/refund.

    Both fields default to 0 when the webhook doesn't carry the
    underlying number — engines downstream tolerate zero.
    """
    metrics: dict[str, Any] = {"profit": 0.0, "conversion": 0.0}

    total = _safe_float(
        payload.get("total_price")
        or payload.get("amount")
        or payload.get("subtotal_price"),
    )

    if polarity == "positive":
        metrics["profit"] = float(total or 0.0)
        metrics["conversion"] = 1.0
    elif polarity == "negative":
        metrics["profit"] = -float(total or 0.0)
        metrics["conversion"] = 0.0
    else:
        metrics["profit"] = float(total or 0.0)

    metrics["topic"] = topic
    metrics["timestamp"] = time.time()
    return metrics


def _safe_float(raw: Any) -> float | None:
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


# ── Singleton ─────────────────────────────────────────────────


def get_webhook_feedback_bridge() -> WebhookFeedbackBridge:
    """Process-wide :class:`WebhookFeedbackBridge` singleton."""
    global _INSTANCE
    with _LOCK:
        if _INSTANCE is None:
            _INSTANCE = WebhookFeedbackBridge()
    return _INSTANCE


def reset_webhook_feedback_bridge() -> None:
    """Drop the cached singleton — test fixture only."""
    global _INSTANCE
    with _LOCK:
        _INSTANCE = None
