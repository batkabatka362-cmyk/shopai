"""LLM fallback for the rule-based intent router.

The rule-based ``classify_intent`` covers the curated phrase
index well, but the long tail (creative phrasings, multi-intent
sentences, languages outside English/Mongolian) lands below
``_NO_MATCH_FLOOR``. This module provides a small Anthropic-
backed fallback that activates ONLY when:

  * ``ANTHROPIC_API_KEY`` is set in the environment (so the
    fallback is opt-in by deployment, not by code).
  * The ``anthropic`` SDK is importable.
  * The rule-based pass returned ``engine=None`` (or below
    ``_NO_MATCH_FLOOR``).

The model is asked one question only: pick the best-fitting
engine name from the supplied list, or return ``"unknown"``.
We pass the curated phrase index as inline context so the model
sees what each engine handles. Output is a tiny JSON blob —
parsed defensively; any parse failure is treated as ``unknown``.

Failure modes (graceful):

  * Key missing → ``None`` (caller falls through to the
    rule-based "no match" result).
  * SDK import fails → ``None``.
  * Network timeout / API error → ``None``.
  * Model returns garbage / unknown engine → ``None``.

The fallback never *replaces* a confident rule-based match — it
only fires when the rules already gave up.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

from utils.logger import get_logger

logger = get_logger("brain.intent_llm")

# Anthropic model the fallback uses. Sonnet 4.6 is the default —
# faster and cheaper than Opus, plenty of capacity for a single
# classification call.
_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 200

# Tighter cap on the input that goes to the LLM; the rule-based
# matcher already caps at 1000 chars, so this is a hard ceiling
# in case a misuse path bypasses that.
_MAX_INPUT_CHARS = 1500


@dataclass
class LLMIntentResult:
    """Outcome of an LLM-fallback classification."""

    engine: str
    confidence: float
    reasoning: str


def llm_classify(
    text: str,
    *,
    candidate_engines: list[str],
    phrase_hints: dict[str, list[str]] | None = None,
) -> LLMIntentResult | None:
    """Ask an Anthropic model to pick the best-fit engine.

    Args:
        text: The user's free-form input.
        candidate_engines: The engines the rule-based router
            already knows about. The LLM must pick from this
            list (or return ``"unknown"``); off-list answers
            collapse to ``None``.
        phrase_hints: Optional ``engine → [phrase, ...]`` map so
            the model gets the same vocabulary the rule index
            uses. When omitted, the prompt is shorter but the
            model has less context.

    Returns:
        ``LLMIntentResult`` on a clean classification, or
        ``None`` for any failure mode (key missing, SDK
        unavailable, network error, parse failure, off-list
        answer).
    """
    if not isinstance(text, str) or not text.strip():
        return None
    if not candidate_engines:
        return None
    text = text[:_MAX_INPUT_CHARS]

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.debug("llm_classify skipped: ANTHROPIC_API_KEY not set")
        return None

    client = _build_client(api_key)
    if client is None:
        return None

    prompt = _build_prompt(text, candidate_engines, phrase_hints)
    raw = _call_anthropic(client, prompt)
    if not raw:
        return None

    return _parse_response(raw, allowed_engines=set(candidate_engines))


# ── Internals ──────────────────────────────────────────────────


def _build_client(api_key: str) -> Any | None:
    """Lazy-import the Anthropic SDK and return a configured client.

    Kept lazy so that simply importing this module doesn't fail
    when the SDK isn't installed — the caller (``classify_intent``)
    only invokes ``llm_classify`` after the rule-based pass, so
    the import only runs in the actual fallback path.
    """
    try:
        import anthropic
    except ImportError as exc:
        logger.debug("anthropic SDK not available: %s", exc)
        return None
    try:
        return anthropic.Anthropic(api_key=api_key)
    except Exception as exc:  # noqa: BLE001
        logger.debug("anthropic client init failed: %s", exc)
        return None


def _build_prompt(
    text: str,
    candidate_engines: list[str],
    phrase_hints: dict[str, list[str]] | None,
) -> str:
    """Build the one-shot classification prompt.

    Format is intentionally rigid: the model returns ONE JSON
    object on a single line. Any deviation collapses to
    "unknown" downstream.
    """
    lines: list[str] = [
        "You are routing a Shopify merchant's free-text request to one of "
        "the engines below. Return ONLY a JSON object on one line — no "
        "prose, no code fences. Schema:",
        '{"engine": "<engine_name_or_unknown>", "confidence": <0.0-1.0>, '
        '"reasoning": "<one-sentence why>"}',
        "",
        "Allowed engines:",
    ]
    for engine in candidate_engines:
        hints = (phrase_hints or {}).get(engine, [])
        if hints:
            sample = ", ".join(hints[:6])
            lines.append(f"- {engine} (e.g. {sample})")
        else:
            lines.append(f"- {engine}")

    lines.extend([
        "",
        "If no engine fits, return engine=\"unknown\".",
        "",
        f"Merchant request: {text}",
    ])
    return "\n".join(lines)


def _call_anthropic(client: Any, prompt: str) -> str:
    """Run a single Messages API call and return the text body.

    Empty string on any failure — caller treats empty as
    fallback miss.
    """
    try:
        msg = client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("anthropic call failed: %s", exc)
        return ""

    try:
        # The SDK exposes content as a list of blocks; we only
        # care about the first text block.
        for block in msg.content or []:
            if getattr(block, "type", "") == "text":
                return getattr(block, "text", "") or ""
        return ""
    except Exception as exc:  # noqa: BLE001
        logger.debug("anthropic response parse failed: %s", exc)
        return ""


_JSON_RE = re.compile(r"\{[^{}]*\}", re.DOTALL)


def _parse_response(
    raw: str, *, allowed_engines: set[str],
) -> LLMIntentResult | None:
    """Pull the first JSON object out of ``raw`` and validate.

    Defensive on every field — the model occasionally wraps the
    JSON in stray characters even when asked not to. We extract
    the first ``{...}`` substring and parse from there.
    """
    if not raw:
        return None

    match = _JSON_RE.search(raw)
    if not match:
        logger.debug("llm response had no JSON object: %r", raw[:120])
        return None

    try:
        parsed = json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError) as exc:
        logger.debug("llm response JSON parse failed: %s", exc)
        return None

    engine = str(parsed.get("engine", "")).strip().lower()
    if engine in {"", "unknown", "none", "null"}:
        return None
    if engine not in allowed_engines:
        logger.debug("llm picked off-list engine: %r", engine)
        return None

    try:
        confidence = float(parsed.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))

    reasoning = str(parsed.get("reasoning", "")).strip()[:200]

    return LLMIntentResult(
        engine=engine, confidence=confidence, reasoning=reasoning,
    )
