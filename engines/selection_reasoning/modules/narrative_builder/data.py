"""Narrative Builder — reference data: templates, phrases, and formatting rules.

Templates are organized by decision type and score tier. Transition phrases
keep narratives flowing naturally. Formatting rules define structural
constraints for the output.
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Narrative templates by score tier and section
# ---------------------------------------------------------------------------
NARRATIVE_TEMPLATES: dict[str, dict[str, str]] = {
    "summary": {
        "strong_pick": (
            "{product_name} is a strong recommendation (score: {score:.1f}/100) "
            "for a {goal}-focused strategy, backed by {confidence} confidence."
        ),
        "solid_pick": (
            "{product_name} is a solid choice (score: {score:.1f}/100) "
            "for a {goal}-focused approach, with {confidence} confidence in the data."
        ),
        "cautious_pick": (
            "{product_name} is the best available option (score: {score:.1f}/100) "
            "for a {goal} strategy, though confidence is {confidence} — proceed with caution."
        ),
        "weak_pick": (
            "{product_name} scored {score:.1f}/100, which is below ideal for a "
            "{goal} strategy — consider gathering more data or exploring alternatives."
        ),
    },
    "explanation": {
        "what": (
            "{product_name} achieved a unified score of {score:.1f} out of 100, "
            "reflecting a {margin:.1f}% profit margin, demand score of "
            "{demand_score:.0f}/100, and {competition_level}. This product stood "
            "out from the evaluated candidates across multiple dimensions."
        ),
        "why_strong": (
            "The selection is driven by strong fundamentals: the combination of "
            "healthy margins and solid demand creates a favorable risk-reward "
            "profile. The competitive landscape is manageable, suggesting room "
            "for a new entrant to capture share."
        ),
        "why_moderate": (
            "While not the highest-scoring option on every dimension, this product "
            "offers the best balance across profitability, demand, and risk. "
            "Trade-offs were made deliberately to align with the stated goal."
        ),
        "how_actionable": (
            "Execution is key: start with a small test order to validate margins, "
            "monitor early sales velocity to confirm demand projections, and be "
            "ready to adjust pricing within the first two weeks."
        ),
    },
    "decision_type": {
        "clear_winner": (
            "This was a clear decision — {product_name} outperformed alternatives "
            "by a significant margin across most evaluation criteria."
        ),
        "close_call": (
            "This was a close decision between {product_name} and the runner-up. "
            "The margin of difference was narrow, and the alternative should be "
            "kept as a backup option."
        ),
        "best_of_limited": (
            "{product_name} was selected from a limited pool of candidates. "
            "Consider expanding the product search if initial results "
            "underperform projections."
        ),
    },
}

# ---------------------------------------------------------------------------
# Transition phrases for connecting paragraphs and ideas
# ---------------------------------------------------------------------------
TRANSITION_PHRASES: dict[str, str] = {
    "supporting": "Additionally,",
    "contrasting": "However,",
    "building": "Building on this,",
    "concluding": "In summary,",
    "qualifying": "It is worth noting that",
    "emphasizing": "Importantly,",
    "risk_intro": "On the risk side,",
    "data_intro": "The data shows that",
    "action_intro": "Moving forward,",
    "caveat": "That said,",
}

# ---------------------------------------------------------------------------
# Formatting rules for narrative structure
# ---------------------------------------------------------------------------
FORMATTING_RULES: dict[str, Any] = {
    "max_word_count": 500,
    "min_word_count": 50,
    "min_data_points": 3,
    "max_paragraphs": 5,
    "min_key_points": 3,
    "max_key_points": 10,
    "summary_max_sentences": 2,
    "paragraph_max_sentences": 5,
    "avoid_words": [
        "guaranteed", "perfect", "flawless", "risk-free",
        "absolutely", "definitely", "impossible",
    ],
    "preferred_number_format": "Use specific numbers (72.3, not 'about 70')",
    "tone": "confident but honest — acknowledge uncertainty",
}

# ---------------------------------------------------------------------------
# Score tier labels for narrative use
# ---------------------------------------------------------------------------
SCORE_TIER_LABELS: dict[str, dict[str, Any]] = {
    "excellent": {"min_score": 75, "label": "strong recommendation", "emoji": None},
    "good": {"min_score": 55, "label": "solid choice", "emoji": None},
    "marginal": {"min_score": 40, "label": "acceptable but limited", "emoji": None},
    "weak": {"min_score": 0, "label": "below threshold — proceed with caution", "emoji": None},
}

# ---------------------------------------------------------------------------
# Risk narrative fragments
# ---------------------------------------------------------------------------
RISK_NARRATIVE_FRAGMENTS: dict[str, str] = {
    "minimal": "The risk profile is minimal, with no significant threats identified.",
    "low": "Risk is low and well-contained within normal operating parameters.",
    "moderate": "There are moderate risks that require monitoring but are manageable.",
    "high": "High-level risks have been identified that could materially impact returns.",
    "critical": "Critical risks are present — this selection carries significant downside exposure.",
}
