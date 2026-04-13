"""Brand Voice Enforcer Engine — tone checker.

Checks if text tone matches the brand's expected tone
(formal, casual, motivating, etc.).

All logic is deterministic. No faking, no random numbers.
"""
from __future__ import annotations

import re
from typing import Any


# ---------------------------------------------------------------------------
# Tone keyword indicators
# ---------------------------------------------------------------------------

_TONE_INDICATORS: dict[str, set[str]] = {
    "formal": {
        "therefore", "furthermore", "consequently", "regarding", "accordingly",
        "hereby", "pursuant", "moreover", "thus", "shall", "respectively",
    },
    "casual": {
        "hey", "awesome", "cool", "gonna", "wanna", "yeah", "nope",
        "super", "totally", "kinda", "fun", "love", "amazing", "great",
    },
    "motivating": {
        "achieve", "conquer", "strength", "push", "unstoppable", "champion",
        "powerful", "inspire", "goal", "victory", "determination", "rise",
    },
    "warm": {
        "nurture", "care", "gentle", "support", "comfort", "trust",
        "safe", "together", "family", "heart", "kind", "compassion",
    },
    "authoritative": {
        "premium", "exclusive", "curated", "distinguished", "exceptional",
        "definitive", "standard", "authority", "leading", "expert",
    },
    "adventurous": {
        "discover", "adventure", "explore", "journey", "bold", "fearless",
        "wild", "trail", "frontier", "venture", "expedition", "quest",
    },
    "playful": {
        "fun", "play", "joy", "wonder", "delight", "bright", "happy",
        "cheerful", "whimsical", "surprise", "giggle", "sparkle",
    },
    "passionate": {
        "allure", "desire", "captivate", "radiant", "embrace", "passion",
        "love", "beauty", "sensual", "intimate", "enchanting", "stunning",
    },
}


def check_tone(
    content: list[dict[str, Any]],
    brand_voice: dict[str, Any],
) -> dict[str, Any]:
    """Check tone alignment for each content item.

    Args:
        content: List of content item dicts.
        brand_voice: Brand voice spec with expected tone.

    Returns:
        Structured dict with per-content tone check results.
    """
    try:
        expected_tone = str(brand_voice.get("tone", "")).lower()
        results: list[dict[str, Any]] = []

        for idx, item in enumerate(content):
            text = str(item.get("text", "")).lower()
            words = set(
                w.strip(".,!?;:\"'()") for w in text.split()
            )

            # Score each tone category
            tone_scores: dict[str, int] = {}
            for tone_name, indicators in _TONE_INDICATORS.items():
                tone_scores[tone_name] = len(words & indicators)

            # Detect dominant tone
            if any(tone_scores.values()):
                detected_tone = max(tone_scores, key=lambda k: tone_scores[k])
            else:
                detected_tone = "neutral"

            # Compute match score (0-100)
            # Check how many keywords from expected tone categories appear
            match_score = 0
            issues: list[str] = []

            # Find which tone categories match the expected tone string
            matching_categories = [
                t for t in _TONE_INDICATORS
                if t in expected_tone
            ]

            if matching_categories:
                total_found = sum(tone_scores.get(c, 0) for c in matching_categories)
                # Normalize: each found keyword adds up to ~10 points, cap at 100
                match_score = min(int(total_found * 15), 100)

                if match_score < 50:
                    issues.append(
                        f"Tone reads as '{detected_tone}' but expected '{expected_tone}'"
                    )
                if match_score < 30:
                    issues.append(
                        "Very low alignment with target tone — consider rewriting"
                    )
            else:
                # If no category matches, give a default mid-range score
                match_score = 50
                issues.append(
                    f"Could not assess tone match for '{expected_tone}'"
                )

            # Check for exclamation overuse
            exclamation_count = text.count("!")
            if exclamation_count > 3:
                issues.append("Excessive use of exclamation marks")
                match_score = max(match_score - 10, 0)

            # Check for ALL CAPS words (more than 2)
            original_text = str(item.get("text", ""))
            caps_words = [w for w in original_text.split() if w.isupper() and len(w) > 1]
            if len(caps_words) > 2:
                issues.append("Excessive use of ALL CAPS words")
                match_score = max(match_score - 10, 0)

            results.append({
                "content_idx": idx,
                "detected_tone": detected_tone,
                "tone_match_score": match_score,
                "tone_issues": issues,
            })

        return {
            "status": "success",
            "tone_checks": results,
        }
    except Exception as exc:
        return {
            "status": "error",
            "tone_checks": [],
            "error": f"Tone checking failed: {exc}",
        }
