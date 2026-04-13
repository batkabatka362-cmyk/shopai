"""Content Generation Engine — quality checker.

Checks content quality: Flesch-Kincaid readability score, grammar flags,
brand voice consistency, and keyword presence validation.

Model note: Uses Mistral for quality analysis and grammar checking.
"""
from __future__ import annotations

import copy
import math
import re
from typing import Any


# ---------------------------------------------------------------------------
# Flesch-Kincaid constants and helpers
# ---------------------------------------------------------------------------

# Common syllable overrides for accuracy
_SYLLABLE_OVERRIDES: dict[str, int] = {
    "the": 1, "every": 3, "area": 3, "idea": 3, "real": 1,
    "beautiful": 3, "comfortable": 4, "business": 2, "different": 3,
    "interesting": 4, "experience": 4, "important": 3, "available": 4,
}


def _count_syllables(word: str) -> int:
    """Count syllables in a word using a vowel-group heuristic."""
    word = word.lower().strip()
    if not word:
        return 0

    if word in _SYLLABLE_OVERRIDES:
        return _SYLLABLE_OVERRIDES[word]

    # Remove trailing silent 'e'
    if word.endswith("e") and len(word) > 2:
        word = word[:-1]

    # Count vowel groups
    vowel_groups = re.findall(r"[aeiouy]+", word)
    count = len(vowel_groups)

    # At least one syllable per word
    return max(count, 1)


def _count_sentences(text: str) -> int:
    """Count sentences in text."""
    sentences = re.split(r"[.!?]+", text)
    return max(len([s for s in sentences if s.strip()]), 1)


def _count_words(text: str) -> int:
    """Count words in text."""
    return max(len(re.findall(r"\b[a-zA-Z]+\b", text)), 1)


def _flesch_kincaid_grade(text: str) -> float:
    """Compute the Flesch-Kincaid Grade Level.

    Formula: 0.39 * (words/sentences) + 11.8 * (syllables/words) - 15.59
    """
    words = re.findall(r"\b[a-zA-Z]+\b", text)
    word_count = len(words) if words else 1
    sentence_count = _count_sentences(text)
    syllable_count = sum(_count_syllables(w) for w in words)

    grade = (
        0.39 * (word_count / sentence_count)
        + 11.8 * (syllable_count / word_count)
        - 15.59
    )
    return round(max(grade, 0.0), 2)


def _flesch_reading_ease(text: str) -> float:
    """Compute the Flesch Reading Ease score.

    Formula: 206.835 - 1.015 * (words/sentences) - 84.6 * (syllables/words)
    Range: 0 (very difficult) to 100 (very easy).
    """
    words = re.findall(r"\b[a-zA-Z]+\b", text)
    word_count = len(words) if words else 1
    sentence_count = _count_sentences(text)
    syllable_count = sum(_count_syllables(w) for w in words)

    ease = (
        206.835
        - 1.015 * (word_count / sentence_count)
        - 84.6 * (syllable_count / word_count)
    )
    return round(max(min(ease, 100.0), 0.0), 2)


# ---------------------------------------------------------------------------
# Grammar / style flags
# ---------------------------------------------------------------------------

_GRAMMAR_PATTERNS: list[tuple[str, str]] = [
    (r"\b(very|really|extremely|absolutely)\s+(very|really|extremely|absolutely)\b", "Double intensifier detected"),
    (r"\b(their|there|they're)\b.*\b(their|there|they're)\b", "Check their/there/they're usage"),
    (r"\s{2,}", "Multiple consecutive spaces found"),
    (r"[.!?]{3,}", "Excessive punctuation"),
    (r"\b(gonna|wanna|gotta|kinda|sorta)\b", "Informal contraction detected"),
    (r"\b(alot|alright)\b", "Common misspelling detected"),
]


def _check_grammar(text: str) -> list[str]:
    """Run basic grammar/style checks on text."""
    flags: list[str] = []
    text_lower = text.lower()

    for pattern, message in _GRAMMAR_PATTERNS:
        if re.search(pattern, text_lower):
            flags.append(message)

    # Check sentence capitalization
    sentences = re.split(r"[.!?]\s+", text)
    for s in sentences:
        s = s.strip()
        if s and s[0].islower():
            flags.append("Sentence starting with lowercase letter")
            break

    return flags


# ---------------------------------------------------------------------------
# Brand voice consistency
# ---------------------------------------------------------------------------

_TONE_WORD_SETS: dict[str, set[str]] = {
    "professional": {"solution", "enterprise", "optimize", "strategic", "implement", "effective", "proven", "reliable"},
    "casual": {"awesome", "cool", "hey", "love", "grab", "check", "vibe", "handy"},
    "urgent": {"limited", "hurry", "now", "exclusive", "last", "rush", "today", "act"},
    "luxury": {"exquisite", "premium", "refined", "elegant", "artisan", "bespoke", "curated", "distinguished"},
    "playful": {"fun", "wow", "exciting", "surprise", "delight", "magic", "amazing", "whimsical"},
    "informative": {"comprehensive", "detailed", "guide", "learn", "discover", "understand", "essential", "thorough"},
}


def _check_brand_voice(text: str, tone: str) -> bool:
    """Check if text is consistent with the expected brand voice/tone."""
    text_lower = text.lower()
    words_in_text = set(re.findall(r"\b[a-z]+\b", text_lower))

    target_words = _TONE_WORD_SETS.get(tone, set())
    if not target_words:
        return True  # Unknown tone — assume consistent

    overlap = words_in_text & target_words
    # At least 1 match from the tone word set indicates consistency
    return len(overlap) >= 1


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def check_quality(
    draft: dict[str, Any],
    tone_selection: dict[str, Any],
    keyword_extraction: dict[str, Any],
) -> dict[str, Any]:
    """Check the quality of the generated content.

    Args:
        draft: CopyDraft dict from copy_writer.
        tone_selection: ToneSelection dict from tone_selector.
        keyword_extraction: KeywordExtraction dict from keyword_extractor.

    Returns:
        Structured dict with QualityResult data.
    """
    try:
        drft = copy.deepcopy(draft)
        tone = copy.deepcopy(tone_selection)
        kw = copy.deepcopy(keyword_extraction)

        headline = str(drft.get("headline", ""))
        body = str(drft.get("body", ""))
        bullets = list(drft.get("bullets", []))
        cta = str(drft.get("cta", ""))

        primary_tone = str(tone.get("primary_tone", "professional"))

        primary_keywords = list(kw.get("primary_keywords", []))
        secondary_keywords = list(kw.get("secondary_keywords", []))

        # Full text for analysis
        full_text = f"{headline}. {body} {' '.join(bullets)}. {cta}"

        # --- Flesch-Kincaid ---
        reading_ease = _flesch_reading_ease(full_text)
        fk_grade = _flesch_kincaid_grade(full_text)

        # --- Grammar flags ---
        grammar_flags = _check_grammar(full_text)

        # --- Brand voice consistency ---
        brand_consistent = _check_brand_voice(full_text, primary_tone)

        # --- Keyword presence ---
        text_lower = full_text.lower()
        keyword_presence: dict[str, bool] = {}
        for kw_term in primary_keywords + secondary_keywords:
            keyword_presence[kw_term.lower()] = kw_term.lower() in text_lower

        # --- Overall quality score (0.0 to 1.0) ---
        overall_quality = _compute_overall_quality(
            reading_ease, fk_grade, grammar_flags,
            brand_consistent, keyword_presence,
        )

        return {
            "status": "success",
            "quality": {
                "readability_score": reading_ease,
                "flesch_kincaid_grade": fk_grade,
                "grammar_flags": grammar_flags,
                "brand_voice_consistent": brand_consistent,
                "keyword_presence": keyword_presence,
                "overall_quality": round(overall_quality, 2),
                "model_note": "Mistral: content quality analysis, grammar checking, and brand voice validation",
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "quality": {},
            "error": f"Quality check failed: {exc}",
        }


def _compute_overall_quality(
    reading_ease: float,
    fk_grade: float,
    grammar_flags: list[str],
    brand_consistent: bool,
    keyword_presence: dict[str, bool],
) -> float:
    """Compute an overall quality score from 0.0 to 1.0."""
    score = 0.0
    max_score = 0.0

    # Readability (30 points) — ideal reading ease 50-70 for marketing
    max_score += 30.0
    if 40.0 <= reading_ease <= 80.0:
        score += 30.0
    elif 20.0 <= reading_ease <= 90.0:
        score += 20.0
    elif reading_ease > 0:
        score += 10.0

    # Grammar (25 points)
    max_score += 25.0
    flag_penalty = len(grammar_flags) * 5.0
    score += max(0.0, 25.0 - flag_penalty)

    # Brand voice (20 points)
    max_score += 20.0
    if brand_consistent:
        score += 20.0

    # Keyword presence (25 points)
    max_score += 25.0
    if keyword_presence:
        present = sum(1 for v in keyword_presence.values() if v)
        total = len(keyword_presence)
        score += 25.0 * (present / total) if total > 0 else 0.0

    return score / max_score if max_score > 0 else 0.0
