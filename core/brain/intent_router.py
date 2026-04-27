"""Free-text intent → engine routing.

Closes the AGI audit's #1 gap (Natural Language Intent Router).
Pre-fix the API required structured ``{"task_type": "<engine>",
"params": {...}}``; merchants who don't know engine names cannot
ask "increase my margins" and have the system pick
``discount_strategy`` or ``dynamic_pricing`` for them.

This module classifies free-form text into one of the registered
engine names. It is a *rule-based* matcher in this first cut — a
curated keyword / synonym index over the top engines, scored by
overlap with the tokenised input. An LLM fallback is intentionally
deferred to a follow-up PR so this lands without an Anthropic
SDK dependency or API key requirement.

Usage:

    from core.brain.intent_router import classify_intent

    result = classify_intent("Help me lower my product prices")
    # IntentResult(engine="dynamic_pricing", confidence=0.82,
    #              alternatives=[("discount_strategy", 0.41), ...],
    #              source="rules",
    #              explanation="matched 'lower' + 'price'")

The matcher is intentionally conservative: when nothing scores
above a floor, ``engine`` is ``None`` and the API surface tells
the caller to be more specific or pick from a list. Better to
admit "I don't know" than route to the wrong engine.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from utils.logger import get_logger

logger = get_logger("brain.intent_router")

# Confidence scale notes:
#   * Each engine scores in [0, 1] based on weighted keyword
#     overlap (specific multi-word phrases weight higher than
#     bare nouns).
#   * Above ``_HIGH_CONFIDENCE`` we surface ``confidence: high``
#     in the explanation and rank ``source: rules``.
#   * Below ``_NO_MATCH_FLOOR`` we return ``engine=None``.
_HIGH_CONFIDENCE = 0.65
_NO_MATCH_FLOOR = 0.18

_ALTERNATIVES_RETURNED = 3
_MAX_TEXT_LEN = 1000

# Curated (engine_name, [(weight, keywords)]) index.
#
# Each tuple is a phrase / keyword that signals the engine. Multi-
# word phrases get higher weight because they're less ambiguous
# than bare nouns. Mongolian terms live alongside English so a
# Mongolian-speaking merchant routes correctly without an explicit
# language switch.
#
# When two engines compete (e.g. "lower the price" matches both
# dynamic_pricing and discount_strategy), tie-breaking prefers
# the engine whose specific phrases matched, not the bare-noun
# overlap.
_INTENT_INDEX: dict[str, list[tuple[float, str]]] = {
    "dynamic_pricing": [
        (1.5, "raise price"), (1.5, "raise prices"),
        (1.5, "lower price"), (1.5, "lower prices"),
        (1.5, "increase price"), (1.5, "increase prices"),
        (1.5, "reduce price"), (1.5, "decrease price"),
        (1.5, "adjust price"), (1.5, "adjust pricing"),
        (1.5, "price strategy"), (1.5, "pricing strategy"),
        (1.5, "optimize price"), (1.5, "optimize pricing"),
        (1.2, "margin"), (1.2, "markup"), (1.2, "repricing"),
        (1.0, "price"), (1.0, "pricing"),
        # Mongolian
        (1.5, "үнэ нэмэх"), (1.5, "үнэ багасгах"),
        (1.2, "үнэ"), (1.2, "ашиг"), (1.2, "ашгийг"),
    ],
    "discount_strategy": [
        (1.5, "discount code"), (1.5, "promo code"),
        (1.5, "coupon code"), (1.5, "promotion"),
        (1.5, "create discount"), (1.5, "mint discount"),
        (1.5, "storewide sale"), (1.5, "flash sale"),
        (1.5, "percent off"), (1.2, "% off"),
        (1.2, "discount"), (1.2, "coupon"),
        (1.0, "sale"), (1.0, "promo"),
        # Mongolian
        (1.5, "хямдрал"), (1.5, "купон"),
        (1.2, "хямдр"), (1.2, "сэйл"),
    ],
    "loyalty": [
        (1.5, "loyalty program"), (1.5, "loyal customer"),
        (1.5, "vip reward"), (1.5, "tier reward"),
        (1.5, "reward customer"), (1.5, "thank loyal"),
        (1.2, "loyalty"), (1.2, "reward"), (1.2, "tier"),
        (1.0, "vip"),
        # Mongolian
        (1.5, "vnenkh xerelegch"), (1.2, "loyalty"),
    ],
    "affiliate": [
        (1.5, "affiliate commission"), (1.5, "pay commission"),
        (1.5, "partner payout"), (1.5, "affiliate program"),
        (1.5, "referral payout"), (1.2, "commission"),
        (1.2, "affiliate"), (1.2, "partner"), (1.0, "referral"),
    ],
    "tag_management": [
        (1.5, "tag products"), (1.5, "auto tag"),
        (1.5, "product tag"), (1.5, "category tag"),
        (1.5, "organize products"), (1.2, "tagging"),
        (1.2, "tags"), (1.0, "tag"),
    ],
    "search_optimization": [
        (1.5, "seo title"), (1.5, "seo description"),
        (1.5, "search ranking"), (1.5, "seo optimize"),
        (1.5, "search optimize"), (1.5, "meta title"),
        (1.5, "meta description"), (1.2, "seo"),
        (1.2, "search rank"), (1.0, "search"),
    ],
    "product_lifecycle": [
        (1.5, "archive product"), (1.5, "kill product"),
        (1.5, "retire product"), (1.5, "discontinue product"),
        (1.5, "declining product"), (1.5, "unpublish product"),
        (1.2, "lifecycle"), (1.2, "archive"),
        (1.0, "retire"), (1.0, "discontinue"),
    ],
    "content_generation": [
        (1.5, "product description"), (1.5, "generate description"),
        (1.5, "rewrite description"), (1.5, "content rewrite"),
        (1.5, "improve copy"), (1.5, "generate content"),
        (1.2, "description"), (1.2, "copywriting"),
        (1.0, "copy"), (1.0, "content"),
    ],
    "inventory": [
        (1.5, "stock level"), (1.5, "inventory level"),
        (1.5, "out of stock"), (1.5, "low stock"),
        (1.5, "restock"), (1.5, "inventory adjust"),
        (1.2, "inventory"), (1.2, "stock"), (1.0, "warehouse"),
        # Mongolian
        (1.5, "агуулах"), (1.2, "нөөц"),
    ],
    "cart_recovery": [
        (1.5, "abandoned cart"), (1.5, "cart abandonment"),
        (1.5, "recover cart"), (1.5, "cart recovery"),
        (1.2, "cart"), (1.0, "abandoned"),
    ],
    "browse_recovery": [
        (1.5, "browse abandonment"), (1.5, "browse recovery"),
        (1.5, "browsed without buying"), (1.5, "viewed product"),
        (1.2, "browse"), (1.0, "viewer"),
    ],
    "churn_prediction": [
        (1.5, "predict churn"), (1.5, "churn risk"),
        (1.5, "customer churn"), (1.5, "lapsing customer"),
        (1.2, "churn"), (1.2, "retention"),
        (1.0, "lapsing"), (1.0, "win back"),
    ],
    "cohort_analysis": [
        (1.5, "customer cohort"), (1.5, "cohort analysis"),
        (1.5, "ltv analysis"), (1.5, "lifetime value"),
        (1.2, "cohort"), (1.2, "ltv"), (1.0, "lifetime"),
    ],
    "bundle": [
        (1.5, "product bundle"), (1.5, "create bundle"),
        (1.5, "bundle deal"), (1.5, "bundle products"),
        (1.2, "bundle"), (1.0, "package"),
    ],
    "upsell": [
        (1.5, "upsell offer"), (1.5, "cross sell"),
        (1.5, "cross-sell"), (1.5, "post purchase"),
        (1.5, "buy with"), (1.2, "upsell"),
        (1.0, "upgrade"),
    ],
    "competitor_analysis": [
        (1.5, "competitor analysis"), (1.5, "compare competitor"),
        (1.5, "competitor price"), (1.5, "monitor competitor"),
        (1.2, "competitor"), (1.2, "competition"),
        (1.0, "rival"),
    ],
    "ads_spy": [
        (1.5, "winning ad"), (1.5, "ad spy"),
        (1.5, "spy on ad"), (1.5, "competitor ad"),
        (1.5, "facebook ad"), (1.5, "tiktok ad"),
        (1.2, "ad creative"), (1.0, "ads"),
    ],
    "creative": [
        (1.5, "ad creative"), (1.5, "generate creative"),
        (1.5, "video script"), (1.5, "ad copy"),
        (1.5, "image generation"), (1.5, "creative asset"),
        (1.2, "creative"), (1.0, "asset"),
    ],
    "roas_guardrails": [
        (1.5, "roas guardrail"), (1.5, "ad spend"),
        (1.5, "kill underperforming"), (1.5, "scale winning"),
        (1.5, "roas threshold"), (1.2, "roas"),
        (1.2, "guardrail"),
    ],
    "fraud_detection": [
        (1.5, "fraud detection"), (1.5, "suspicious order"),
        (1.5, "chargeback risk"), (1.5, "risky order"),
        (1.2, "fraud"), (1.2, "chargeback"),
        (1.0, "suspicious"),
    ],
    "shipping": [
        (1.5, "shipping rate"), (1.5, "shipping cost"),
        (1.5, "shipping zone"), (1.5, "shipping label"),
        (1.2, "shipping"), (1.2, "delivery"), (1.0, "freight"),
    ],
    "tax": [
        (1.5, "tax calculation"), (1.5, "tax compliance"),
        (1.5, "vat"), (1.5, "sales tax"),
        (1.2, "tax"),
    ],
    "checkout_optimizer": [
        (1.5, "checkout optimization"), (1.5, "checkout flow"),
        (1.5, "improve checkout"), (1.2, "checkout"),
    ],
    "wholesale_b2b": [
        (1.5, "b2b pricing"), (1.5, "wholesale price"),
        (1.5, "bulk discount"), (1.5, "trade pricing"),
        (1.2, "wholesale"), (1.2, "b2b"),
    ],
}

_PHRASE_NORMALISE = re.compile(r"[^\w\s%]", re.UNICODE)


@dataclass
class IntentResult:
    """Outcome of an intent-classification request.

    ``engine`` is ``None`` when no candidate scored above
    ``_NO_MATCH_FLOOR``. ``alternatives`` is always present even
    on a no-match so the API can render "did you mean X?".
    """

    engine: str | None
    confidence: float
    alternatives: list[tuple[str, float]] = field(default_factory=list)
    source: str = "rules"
    explanation: str = ""
    matched_keywords: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "confidence": round(self.confidence, 3),
            "alternatives": [
                {"engine": e, "confidence": round(c, 3)}
                for e, c in self.alternatives
            ],
            "source": self.source,
            "explanation": self.explanation,
            "matched_keywords": self.matched_keywords,
        }


def classify_intent(
    text: str,
    *,
    language: str = "auto",
    available_engines: set[str] | None = None,
) -> IntentResult:
    """Map free-form ``text`` to the best-match engine name.

    Args:
        text: User input. Capped at ``_MAX_TEXT_LEN`` characters
            so a malformed request can't burn unbounded matcher
            time.
        language: Hint for future LLM fallback. Currently
            ignored — the rule-based path is language-agnostic
            because the index includes Mongolian and English
            keywords side-by-side.
        available_engines: Optional whitelist used by callers
            who only want to route within their slice of
            engines (e.g. integration tests). When ``None`` the
            full ``_INTENT_INDEX`` is consulted.

    Returns:
        :class:`IntentResult`. ``engine`` is ``None`` on a
        no-match; check ``alternatives`` for runner-ups.
    """
    if not isinstance(text, str) or not text.strip():
        return IntentResult(
            engine=None, confidence=0.0,
            source="rules",
            explanation="empty input",
        )
    text = text[:_MAX_TEXT_LEN]
    norm = _normalise(text)
    input_tokens = _stemmed_tokens(norm)

    scores: dict[str, float] = {}
    matched: dict[str, list[str]] = {}

    for engine, phrases in _INTENT_INDEX.items():
        if available_engines is not None and engine not in available_engines:
            continue
        engine_score = 0.0
        engine_matched: list[str] = []
        for weight, phrase in phrases:
            phrase_norm = _normalise(phrase)
            if not phrase_norm:
                continue
            # Tier 1 — contiguous substring (strongest signal).
            if phrase_norm in norm:
                engine_score += weight
                engine_matched.append(phrase)
                continue
            # Tier 2 — every phrase token (stemmed) appears in
            # the input. Catches "lower my product prices" vs
            # the phrase "lower price". Down-weighted to 70% so
            # contiguous matches still win.
            phrase_tokens = _stemmed_tokens(phrase_norm)
            if phrase_tokens and phrase_tokens.issubset(input_tokens):
                engine_score += weight * 0.7
                engine_matched.append(phrase)
        if engine_score > 0:
            scores[engine] = engine_score
            matched[engine] = engine_matched

    if not scores:
        # Zero rule matches — try the LLM fallback before
        # surrendering. Same opt-in semantics as the
        # below-floor branch below.
        llm_result = _try_llm_fallback(text)
        if llm_result is not None:
            return IntentResult(
                engine=llm_result.engine,
                confidence=llm_result.confidence,
                source="llm",
                explanation=llm_result.reasoning or (
                    "LLM-classified after rule-based pass had "
                    "no keyword match"
                ),
            )

        return IntentResult(
            engine=None, confidence=0.0,
            source="rules",
            explanation=(
                "no engine keyword matched — "
                "try 'increase prices' or 'create discount'"
            ),
        )

    # Convert raw weighted scores into a [0, 1] confidence by
    # comparing each engine's score to the theoretical max
    # (sum of its phrase weights). This way a partial match on
    # an engine with many phrases doesn't dominate a full match
    # on an engine with few.
    normalised: list[tuple[str, float]] = []
    for engine, raw in scores.items():
        max_possible = sum(w for w, _ in _INTENT_INDEX[engine])
        if max_possible == 0:
            confidence = 0.0
        else:
            # Square-root softens the curve so a single multi-
            # word match still produces a respectable confidence.
            confidence = min(1.0, (raw / max_possible) ** 0.5)
        normalised.append((engine, confidence))

    normalised.sort(key=lambda x: x[1], reverse=True)
    top_engine, top_confidence = normalised[0]

    if top_confidence < _NO_MATCH_FLOOR:
        # Rule-based pass gave up. Try the LLM fallback before
        # surrendering. The fallback is opt-in by deployment
        # (only fires when ANTHROPIC_API_KEY is set + the SDK
        # is importable) so production code without a key
        # behaves exactly as before.
        llm_result = _try_llm_fallback(text)
        if llm_result is not None:
            return IntentResult(
                engine=llm_result.engine,
                confidence=llm_result.confidence,
                alternatives=[
                    (e, c) for e, c in normalised[:_ALTERNATIVES_RETURNED]
                ],
                source="llm",
                explanation=llm_result.reasoning or (
                    f"LLM-classified after rule-based fallback "
                    f"(rules best: '{top_engine}' at "
                    f"{top_confidence:.2f})"
                ),
            )

        return IntentResult(
            engine=None,
            confidence=top_confidence,
            alternatives=[
                (e, c) for e, c in normalised[:_ALTERNATIVES_RETURNED]
            ],
            source="rules",
            explanation=(
                f"weak match — best candidate '{top_engine}' "
                f"scored {top_confidence:.2f} (floor "
                f"{_NO_MATCH_FLOOR})"
            ),
        )

    qualifier = "high" if top_confidence >= _HIGH_CONFIDENCE else "medium"
    return IntentResult(
        engine=top_engine,
        confidence=top_confidence,
        alternatives=[
            (e, c) for e, c in normalised[1:_ALTERNATIVES_RETURNED + 1]
        ],
        source="rules",
        explanation=(
            f"{qualifier} confidence — matched "
            f"{', '.join(matched[top_engine][:3])}"
        ),
        matched_keywords=matched[top_engine],
    )


def _try_llm_fallback(text: str):
    """Best-effort LLM classification when the rule-based pass
    yielded a below-floor match.

    Lazy-imports :mod:`core.brain.intent_llm` so a missing
    Anthropic SDK can't break the rule-based hot path. Returns
    ``LLMIntentResult`` on success, ``None`` on any failure
    (key missing / SDK absent / network / parse).
    """
    try:
        from core.brain.intent_llm import llm_classify
    except Exception as exc:  # noqa: BLE001
        logger.debug("intent_llm import failed: %s", exc)
        return None

    phrase_hints = {
        engine: [phrase for _, phrase in phrases][:6]
        for engine, phrases in _INTENT_INDEX.items()
    }
    try:
        return llm_classify(
            text,
            candidate_engines=list(_INTENT_INDEX.keys()),
            phrase_hints=phrase_hints,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("llm_classify raised: %s", exc)
        return None


def list_supported_engines() -> list[str]:
    """Engines the rule-based router currently knows.

    Surface for the API: a caller hitting the ``/api/intent``
    endpoint with no prior knowledge of which engines are
    routable can hit this list to see the menu.
    """
    return sorted(_INTENT_INDEX.keys())


def _normalise(text: str) -> str:
    """Lower-case + strip punctuation (keep ``%`` for ``%off``)."""
    cleaned = _PHRASE_NORMALISE.sub(" ", text)
    return " ".join(cleaned.lower().split())


def _stemmed_tokens(text: str) -> set[str]:
    """Word-level token set with naive trailing-``s`` stripping.

    The intent index speaks in either singular ("lower price") or
    plural ("raise prices") forms; the merchant might type either.
    Stripping a trailing ``s`` from any token of length ≥ 4
    collapses common pluralisation without bringing in a real
    stemmer. The 4-char floor keeps short tokens like "ads" intact.
    """
    out: set[str] = set()
    for word in text.split():
        if len(word) >= 4 and word.endswith("s") and not word.endswith("ss"):
            out.add(word[:-1])
        else:
            out.add(word)
    return out
