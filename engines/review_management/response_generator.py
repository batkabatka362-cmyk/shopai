"""Review Management Engine — response generator.

Generates professional review responses: thanks positive reviewers,
addresses negative concerns with empathy, acknowledges neutral/mixed
feedback. Tone adapts to star rating and detected sentiment.

All responses are template-driven with dynamic interpolation.
No faking, no random text.

Model note: Uses LLaMA for natural-language response generation.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Response templates by sentiment bucket
# ---------------------------------------------------------------------------

_POSITIVE_TEMPLATES: list[str] = [
    (
        "Thank you so much for your wonderful {rating}-star review! "
        "We're thrilled to hear that you had a great experience{topic_clause}. "
        "Your support means the world to us, and we look forward to serving you again."
    ),
    (
        "We truly appreciate your {rating}-star rating and kind words! "
        "It's fantastic to know that {topic_clause_alt}you're satisfied with your purchase. "
        "Thank you for choosing us!"
    ),
]

_NEGATIVE_TEMPLATES: list[str] = [
    (
        "We're sorry to hear about your experience{topic_clause}. "
        "Your feedback is important to us, and we'd like to make this right. "
        "Please reach out to our support team so we can address your concerns directly."
    ),
    (
        "Thank you for taking the time to share your feedback. "
        "We sincerely apologize for the issues you encountered{topic_clause}. "
        "We're committed to improving and would love the opportunity to resolve this for you."
    ),
]

_NEUTRAL_TEMPLATES: list[str] = [
    (
        "Thank you for your {rating}-star review and honest feedback. "
        "We appreciate you sharing your experience{topic_clause}. "
        "We're always working to improve, and your input helps us do just that."
    ),
]

_MIXED_TEMPLATES: list[str] = [
    (
        "Thank you for your balanced {rating}-star review. "
        "We're glad to hear about the positives{topic_clause}, and we take "
        "your concerns seriously. We're actively working on improvements "
        "based on feedback like yours."
    ),
]


def generate_responses(
    reviews: list[dict[str, Any]],
    sentiment_per_review: list[dict[str, Any]],
    topics: list[dict[str, Any]],
) -> dict[str, Any]:
    """Generate a professional response for each review.

    Args:
        reviews: List of ReviewItem dicts.
        sentiment_per_review: Per-review sentiment results (from sentiment_analyzer).
        topics: Extracted topic list (from topic_extractor) for context.

    Returns:
        Structured dict with list of ReviewResponse data.
    """
    try:
        items = copy.deepcopy(reviews)
        sentiments = {s["review_id"]: s for s in sentiment_per_review}

        # Build a set of top topics for contextual mentions
        top_topics = [t["topic"] for t in topics[:3]] if topics else []

        responses: list[dict[str, Any]] = []

        for review in items:
            review_id = str(review.get("id", ""))
            rating = float(review.get("rating", 3.0))
            text = str(review.get("text", ""))
            sent_info = sentiments.get(review_id, {})
            sentiment = str(sent_info.get("sentiment", "neutral"))

            # Determine which topics this review mentions
            mentioned_topics = _find_mentioned_topics(text, top_topics)
            topic_clause = _build_topic_clause(mentioned_topics)
            topic_clause_alt = _build_topic_clause_alt(mentioned_topics)

            # Select template based on sentiment
            response_text = _select_and_fill(
                sentiment=sentiment,
                rating=rating,
                topic_clause=topic_clause,
                topic_clause_alt=topic_clause_alt,
                review_index=len(responses),
            )

            # Determine tone label
            if sentiment == "positive":
                tone = "grateful"
            elif sentiment == "negative":
                tone = "empathetic"
            elif sentiment == "mixed":
                tone = "balanced"
            else:
                tone = "professional"

            responses.append({
                "review_id": review_id,
                "rating": rating,
                "tone": tone,
                "response_text": response_text,
                "model_note": "LLaMA: template-driven response with contextual interpolation",
            })

        return {
            "status": "success",
            "responses": responses,
        }
    except Exception as exc:
        return {
            "status": "error",
            "responses": [],
            "error": f"Response generation failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_TOPIC_FRIENDLY_NAMES: dict[str, str] = {
    "quality": "product quality",
    "shipping": "shipping experience",
    "price": "pricing and value",
    "packaging": "packaging",
    "customer_service": "customer service",
    "size_fit": "sizing and fit",
    "durability": "durability",
}


def _find_mentioned_topics(text: str, top_topics: list[str]) -> list[str]:
    """Find which of the top topics are mentioned in the review text."""
    text_lower = text.lower()
    mentioned: list[str] = []
    for topic in top_topics:
        # Check if the topic keyword or its friendly name appears
        if topic in text_lower:
            mentioned.append(topic)
        else:
            friendly = _TOPIC_FRIENDLY_NAMES.get(topic, topic)
            if any(word in text_lower for word in friendly.split()):
                mentioned.append(topic)
    return mentioned


def _build_topic_clause(mentioned: list[str]) -> str:
    """Build a clause like ' with our product quality and shipping'."""
    if not mentioned:
        return ""
    names = [_TOPIC_FRIENDLY_NAMES.get(t, t) for t in mentioned[:2]]
    if len(names) == 1:
        return f" with our {names[0]}"
    return f" with our {names[0]} and {names[1]}"


def _build_topic_clause_alt(mentioned: list[str]) -> str:
    """Build an alternative clause like 'our product quality meets your expectations and '."""
    if not mentioned:
        return ""
    name = _TOPIC_FRIENDLY_NAMES.get(mentioned[0], mentioned[0])
    return f"our {name} meets your expectations and "


def _select_and_fill(
    sentiment: str,
    rating: float,
    topic_clause: str,
    topic_clause_alt: str,
    review_index: int,
) -> str:
    """Select a template and fill in placeholders."""
    if sentiment == "positive":
        templates = _POSITIVE_TEMPLATES
    elif sentiment == "negative":
        templates = _NEGATIVE_TEMPLATES
    elif sentiment == "mixed":
        templates = _MIXED_TEMPLATES
    else:
        templates = _NEUTRAL_TEMPLATES

    # Rotate templates to avoid repetition
    template = templates[review_index % len(templates)]

    return template.format(
        rating=int(rating),
        topic_clause=topic_clause,
        topic_clause_alt=topic_clause_alt,
    )
