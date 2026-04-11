"""Brand Voice Enforcer Engine — content analyzer.

Analyzes text for structural metrics: word count, sentence count,
average sentence length, formality score, and vocabulary alignment.

All logic is deterministic. No faking, no random numbers.
"""
from __future__ import annotations

import re
from typing import Any


# ---------------------------------------------------------------------------
# Formality indicators
# ---------------------------------------------------------------------------

_FORMAL_WORDS = {
    "therefore", "furthermore", "consequently", "nevertheless", "accordingly",
    "regarding", "pursuant", "hereby", "wherein", "aforementioned",
    "henceforth", "notwithstanding", "whereas", "moreover", "thus",
}

_INFORMAL_WORDS = {
    "hey", "awesome", "cool", "gonna", "wanna", "gotta", "yeah", "nope",
    "lol", "omg", "btw", "tbh", "imo", "literally", "basically", "stuff",
    "things", "super", "totally", "kinda", "sorta", "yep", "nah",
}


def analyze_content(
    content: list[dict[str, Any]],
    brand_voice: dict[str, Any],
) -> dict[str, Any]:
    """Analyze content items for structural and voice metrics.

    Args:
        content: List of content item dicts with type and text.
        brand_voice: Brand voice spec with tone, vocabulary.

    Returns:
        Structured dict with per-content analysis.
    """
    try:
        on_brand_vocab = set(
            w.lower() for w in brand_voice.get("vocabulary", [])
        )
        analyses: list[dict[str, Any]] = []

        for idx, item in enumerate(content):
            text = str(item.get("text", ""))
            words = text.split()
            word_count = len(words)

            # Sentence splitting
            sentences = [s.strip() for s in re.split(r'[.!?]+', text) if s.strip()]
            sentence_count = max(len(sentences), 1)
            avg_sentence_length = round(word_count / sentence_count, 1)

            # Formality score: -1.0 (very informal) to 1.0 (very formal)
            lower_words = set(w.lower().strip(".,!?;:\"'()") for w in words)
            formal_count = len(lower_words & _FORMAL_WORDS)
            informal_count = len(lower_words & _INFORMAL_WORDS)
            total_indicators = formal_count + informal_count
            if total_indicators > 0:
                formality_score = round(
                    (formal_count - informal_count) / total_indicators, 2,
                )
            else:
                formality_score = 0.0

            # Vocabulary alignment: fraction of on-brand words found
            if on_brand_vocab:
                found = sum(1 for w in on_brand_vocab if w in text.lower())
                vocab_alignment = round(found / len(on_brand_vocab), 2)
            else:
                vocab_alignment = 1.0

            analyses.append({
                "content_idx": idx,
                "word_count": word_count,
                "sentence_count": sentence_count,
                "avg_sentence_length": avg_sentence_length,
                "formality_score": formality_score,
                "vocabulary_alignment": vocab_alignment,
            })

        return {
            "status": "success",
            "analyses": analyses,
        }
    except Exception as exc:
        return {
            "status": "error",
            "analyses": [],
            "error": f"Content analysis failed: {exc}",
        }
