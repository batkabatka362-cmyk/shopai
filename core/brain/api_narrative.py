"""Surface engine decisions through the API as human-readable narratives.

Pre-fix the API returned bare result dicts: ``status``, ``result``,
``error``, ``elapsed_seconds``. Operators saw stack-trace strings on
failures and opaque JSON on success. The brain layer already
computes ``attribution`` (per-rule audit trail in
``core.brain.decision_engine.Decision``) and the
``DecisionNarrator`` produces plain-language summaries for cycle
results — but neither reached the HTTP surface. This bridges the
gap.

``enrich_response`` is a pure function:

  * Detects whether the result is a success/error/empty/cached.
  * Walks known result shapes (engine output, decision payload,
    chain output) for a ``choice``/``action``/``decision``,
    ``reason``/``why``, and ``score``/``confidence``.
  * Compresses any ``attribution`` list into a top-3 ``why`` summary.
  * Adds a ``narrative`` field — a one-line "what just happened"
    string a non-engineer can read.
  * Adds a ``next_action`` hint when the shape suggests an obvious
    follow-up (apply the recommendation, retry, contact support).

It mutates a shallow copy and returns it; the original result is
left untouched. Failures inside the enricher MUST NOT propagate —
the API response is more important than the narrative.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

logger = get_logger("brain.api_narrative")

_MAX_ATTRIBUTION = 3
_MAX_NARRATIVE_LEN = 240


def enrich_response(
    result: Any,
    *,
    task_type: str = "",
    params: dict[str, Any] | None = None,
) -> Any:
    """Return ``result`` with ``narrative`` / ``next_action`` /
    ``attribution_summary`` surfaced.

    Args:
        result: The raw response from
            ``MainOrchestrator.submit_task`` (or any sibling
            method). Typically a dict with ``status``, ``result``,
            ``error``. Non-dict inputs are returned unchanged.
        task_type: Engine / capability name. Used to make the
            narrative specific ("dynamic_pricing produced…")
            instead of generic.
        params: Original request params. Used so the narrative
            can reference what the caller actually asked for.

    Returns:
        Shallow-copied dict with three new keys:
          * ``narrative`` — single-line plain-language summary.
          * ``next_action`` — string hint or ``None``.
          * ``attribution_summary`` — list of up to 3
            ``{source, description, impact}`` entries lifted out
            of any nested ``attribution`` field.
        On non-dict input or any internal failure the original
        ``result`` is returned unchanged.
    """
    try:
        return _enrich(result, task_type=task_type, params=params)
    except Exception as exc:  # noqa: BLE001
        logger.debug("enrich_response failed: %s", exc)
        return result


def _enrich(
    result: Any,
    *,
    task_type: str,
    params: dict[str, Any] | None,
) -> Any:
    if not isinstance(result, dict):
        return result

    enriched = dict(result)
    status = str(enriched.get("status", "")).lower()
    error = enriched.get("error")

    inner = enriched.get("result")
    if not isinstance(inner, dict):
        inner = {}

    confidence = (
        enriched.get("confidence_score")
        or inner.get("confidence_score")
        or enriched.get("confidence")
        or inner.get("confidence")
    )
    confidence_str = _format_confidence(confidence)

    choice = (
        inner.get("decision")
        or inner.get("action")
        or inner.get("choice")
        or enriched.get("decision")
    )
    reason = (
        inner.get("reason")
        or inner.get("why")
        or inner.get("explanation")
    )

    attribution = _collect_attribution(enriched)
    if attribution:
        enriched["attribution_summary"] = attribution[:_MAX_ATTRIBUTION]
    else:
        enriched["attribution_summary"] = []

    narrative = _build_narrative(
        task_type=task_type,
        status=status,
        error=error,
        choice=choice,
        reason=reason,
        confidence_str=confidence_str,
        params=params,
        cached=bool(enriched.get("_cached")),
    )
    if narrative:
        enriched["narrative"] = narrative[:_MAX_NARRATIVE_LEN]

    enriched["next_action"] = _suggest_next_action(
        status=status,
        error=error,
        inner=inner,
        task_type=task_type,
    )

    return enriched


def _build_narrative(
    *,
    task_type: str,
    status: str,
    error: Any,
    choice: Any,
    reason: Any,
    confidence_str: str,
    params: dict[str, Any] | None,
    cached: bool,
) -> str:
    label = task_type or "engine"

    if status in ("error", "failed"):
        err_str = str(error) if error else "no error message"
        hint = _diagnose_error(err_str)
        head = f"{label} failed: {err_str}"
        return f"{head}. {hint}" if hint else head

    if status not in ("completed", "success", "ok"):
        if status:
            return f"{label} returned status={status}; result is incomplete"

    bits: list[str] = []
    if cached:
        bits.append(f"{label} (cached)")
    else:
        bits.append(label)

    if choice:
        bits.append(f"chose {choice}")
    elif params:
        target = params.get("id") or params.get("product_id") or params.get("store_id")
        if target:
            bits.append(f"processed {target}")

    if reason:
        bits.append(f"because {str(reason)[:120]}")

    if confidence_str:
        bits.append(f"(confidence {confidence_str})")

    return " ".join(bits)


def _suggest_next_action(
    *,
    status: str,
    error: Any,
    inner: dict[str, Any],
    task_type: str,
) -> str | None:
    if status in ("error", "failed"):
        err_str = str(error or "").lower()
        if "no engine" in err_str:
            return f"verify task_type='{task_type}' is registered in engines.registry"
        if "scope" in err_str or "access denied" in err_str:
            return "extend Shopify Admin scopes for this capability and reinstall the app"
        if "credentials" in err_str or "token" in err_str:
            return "set SHOPAI_SHOPIFY_URL and SHOPAI_SHOPIFY_KEY in .env"
        return "retry with verbose logging to capture the failure context"

    apply_results = inner.get("apply_results") or inner.get("minted_codes")
    if isinstance(apply_results, list) and apply_results:
        return f"review {len(apply_results)} writeback result(s) for skip reasons"

    recs = (
        inner.get("recommendations")
        or inner.get("assignments")
        or inner.get("meta_recommendations")
    )
    if isinstance(recs, list) and recs:
        return (
            f"opt in to apply by passing apply_X=True "
            f"(found {len(recs)} recommendations)"
        )

    return None


def _collect_attribution(payload: dict[str, Any]) -> list[dict[str, Any]]:
    nested = payload.get("attribution")
    if isinstance(nested, list):
        return [_compact(a) for a in nested if isinstance(a, dict)]

    inner = payload.get("result")
    if isinstance(inner, dict):
        nested = inner.get("attribution")
        if isinstance(nested, list):
            return [_compact(a) for a in nested if isinstance(a, dict)]

    return []


def _compact(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": entry.get("source", ""),
        "description": str(entry.get("description", ""))[:120],
        "impact": entry.get("impact"),
    }


def _format_confidence(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        as_float = float(value)
    except (TypeError, ValueError):
        return ""
    if 0.0 <= as_float <= 1.0:
        return f"{as_float:.0%}"
    if 0.0 <= as_float <= 100.0:
        return f"{as_float:.0f}/100"
    return f"{as_float:.2f}"


def _diagnose_error(err: str) -> str:
    low = err.lower()
    if "no engine" in low or "unknown task" in low:
        return "the requested task type is not wired to any engine"
    if "scope" in low or "access denied" in low:
        return "Shopify rejected the call for missing scopes"
    if "credentials" in low or "token" in low or "unauthor" in low:
        return "Shopify credentials are missing or invalid"
    if "timeout" in low or "timed out" in low:
        return "the upstream call exceeded its time budget"
    return ""
