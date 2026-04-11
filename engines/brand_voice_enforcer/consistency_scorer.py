"""Brand Voice Enforcer Engine — consistency scorer.

Scores overall brand consistency 0-100 by combining tone,
vocabulary, and structural analysis results.

All logic is deterministic. No faking, no random numbers.
"""
from __future__ import annotations

from typing import Any


def score_consistency(
    analyses: list[dict[str, Any]],
    tone_checks: list[dict[str, Any]],
    vocabulary_results: list[dict[str, Any]],
    content: list[dict[str, Any]],
) -> dict[str, Any]:
    """Score brand voice consistency for each content item.

    Args:
        analyses: Per-content structural analysis dicts.
        tone_checks: Per-content tone check dicts.
        vocabulary_results: Per-content vocabulary filter dicts.
        content: Original content items.

    Returns:
        Structured dict with per-content consistency scores and overall.
    """
    try:
        # Build lookup maps by content_idx
        analysis_map = {a["content_idx"]: a for a in analyses}
        tone_map = {t["content_idx"]: t for t in tone_checks}
        vocab_map = {v["content_idx"]: v for v in vocabulary_results}

        scores: list[dict[str, Any]] = []
        total_score = 0

        for idx in range(len(content)):
            analysis = analysis_map.get(idx, {})
            tone = tone_map.get(idx, {})
            vocab = vocab_map.get(idx, {})

            issues: list[str] = []

            # Tone component (40% weight)
            tone_score = int(tone.get("tone_match_score", 50))
            tone_issues = tone.get("tone_issues", [])
            issues.extend(tone_issues)

            # Vocabulary component (30% weight)
            off_brand_count = len(vocab.get("off_brand_words", []))
            on_brand_count = vocab.get("on_brand_word_count", 0)
            if off_brand_count == 0:
                vocab_score = 100
            else:
                # Penalize 15 points per off-brand word, floor at 0
                vocab_score = max(100 - (off_brand_count * 15), 0)
            if off_brand_count > 0:
                issues.append(
                    f"Found {off_brand_count} off-brand word(s): "
                    + ", ".join(vocab.get("off_brand_words", [])[:5])
                )

            # Structure component (30% weight)
            vocab_alignment = float(analysis.get("vocabulary_alignment", 0.5))
            structure_score = int(vocab_alignment * 100)

            # Weighted composite
            composite = int(
                tone_score * 0.4 + vocab_score * 0.3 + structure_score * 0.3
            )
            composite = max(0, min(100, composite))

            scores.append({
                "content_idx": idx,
                "consistency_score": composite,
                "issues": issues,
            })
            total_score += composite

        overall = round(total_score / len(content)) if content else 0

        # Generate recommendations
        recommendations: list[str] = []
        if overall < 50:
            recommendations.append("Content requires significant revision to align with brand voice")
        elif overall < 70:
            recommendations.append("Content partially aligns — review flagged issues and adjust tone")
        elif overall < 90:
            recommendations.append("Content mostly aligns — minor adjustments recommended")
        else:
            recommendations.append("Content strongly aligns with brand voice")

        # Aggregate corrections from vocabulary results
        corrections: list[dict[str, Any]] = []
        for v in vocabulary_results:
            replacements = v.get("suggested_replacements", {})
            for old_word, new_word in replacements.items():
                corrections.append({
                    "content_idx": v.get("content_idx", 0),
                    "original": old_word,
                    "suggested": new_word,
                })

        return {
            "status": "success",
            "scores": scores,
            "overall_score": overall,
            "corrections": corrections,
            "recommendations": recommendations,
        }
    except Exception as exc:
        return {
            "status": "error",
            "scores": [],
            "overall_score": 0,
            "corrections": [],
            "recommendations": [],
            "error": f"Consistency scoring failed: {exc}",
        }
