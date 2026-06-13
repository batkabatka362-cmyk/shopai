"""Deterministic variant generation rules.

3 strategies × 3 variants each = 9 variant slots per product.
Each strategy applies a different copywriting angle to encourage
different customer segments.

Why deterministic (no LLM yet):
  - Operator can preview output offline + reproduce in tests
  - No API key required for variant generation
  - LLM swap-in stays straightforward (replace the rule fn with
    an LLM call producing the same shape)
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class TitleVariant:
    angle: str          # feature / benefit / urgency
    text: str           # the actual title

@dataclass
class DescVariant:
    strategy: str       # short / value_prop / social_proof
    text: str

@dataclass
class PriceVariant:
    label: str          # current / discount_10 / premium_15
    price: float


_STOP_WORDS = {
    "the", "a", "an", "for", "with", "to", "and", "or",
    "of", "in", "on", "is",
}


def _first_meaningful_word(title: str) -> str:
    """Pull the first non-stopword from a title (e.g. 'The Best
    Bamboo Spice Rack' -> 'Best')."""
    for w in re.split(r"\s+", (title or "").strip()):
        if w and w.lower() not in _STOP_WORDS:
            return w
    return ""


def _product_noun(title: str) -> str:
    """Extract the likely product noun (last 1-3 meaningful
    words, before any descriptive suffix)."""
    words = re.split(r"\s+", (title or "").strip())
    meaningful = [
        w for w in words
        if w and w.lower() not in _STOP_WORDS
    ]
    if not meaningful:
        return "Product"
    # Take last 2-3 meaningful words.
    take = meaningful[-3:] if len(meaningful) >= 3 else meaningful
    return " ".join(take)


def title_variants(
    *, title: str, category: str = "",
) -> list[TitleVariant]:
    """Generate 3 alternative title angles.

    Strategies:
      - feature: leads with the standout product feature
      - benefit: leads with the customer outcome
      - urgency: adds scarcity / time pressure framing
    """
    if not title:
        return []
    base = title.strip()
    noun = _product_noun(base)
    feature_lead = _first_meaningful_word(base) or noun

    variants: list[TitleVariant] = []

    # Feature angle: leads with the standout feature word.
    variants.append(TitleVariant(
        angle="feature",
        text=f"{feature_lead}: The {noun} That Actually Works",
    ))

    # Benefit angle: leads with the customer outcome.
    cat = (category or "").strip().lower()
    benefit_phrase = {
        "skincare": "Glow Up With",
        "makeup": "Look Polished With",
        "haircare": "Stronger Hair Starts With",
        "bodycare": "Soft Skin All Day With",
        "kitchen": "Cook Smarter With",
        "decor": "Transform Any Room With",
        "tableware": "Set the Mood With",
        "bath": "Spa Days at Home With",
        "bedding": "Better Sleep With",
        "audio": "Hear Every Detail With",
        "charging": "Never Run Out of Power With",
        "computing": "Work Faster With",
        "tops": "Effortless Style With",
        "bottoms": "All-Day Comfort With",
        "dresses": "Turn Heads With",
        "shoes": "Walk Confident In",
        "accessories": "Complete Your Look With",
        "jewelry": "Subtle Elegance With",
        "coffee": "Better Mornings With",
        "tea": "Slow Down With",
        "chocolate": "Indulge in",
        "pantry": "Elevate Every Meal With",
    }.get(cat, "Discover")
    variants.append(TitleVariant(
        angle="benefit",
        text=f"{benefit_phrase} {noun}",
    ))

    # Urgency angle: scarcity framing.
    variants.append(TitleVariant(
        angle="urgency",
        text=f"Limited Edition {noun} — Selling Fast",
    ))

    return variants


def description_variants(
    *, description: str, title: str, category: str = "",
) -> list[DescVariant]:
    """Generate 3 description copy strategies.

    Strategies:
      - short: punchy 1-2 sentence summary
      - value_prop: feature -> benefit chain
      - social_proof: testimonial-style framing
    """
    if not title:
        return []
    noun = _product_noun(title)

    # Strip HTML if any (descriptions are often body_html).
    plain = re.sub(r"<[^>]+>", "", description or "").strip()
    summary = plain[:120] if plain else f"Premium {noun.lower()} you'll love."

    variants: list[DescVariant] = []

    # Short: lean punchy version
    variants.append(DescVariant(
        strategy="short",
        text=f"<p><strong>{summary}</strong></p>",
    ))

    # Value-prop: feature -> benefit chain
    cat = (category or "").lower()
    benefit = {
        "skincare": "visibly smoother, healthier skin",
        "makeup": "a flawless look that lasts all day",
        "haircare": "stronger, shinier hair in weeks",
        "kitchen": "meals you're proud to serve",
        "decor": "a space that finally feels like home",
        "audio": "music the way artists intended",
        "charging": "the freedom to use your devices anywhere",
        "computing": "a setup that scales with your work",
        "coffee": "better mornings, every morning",
    }.get(cat, "the results you're looking for")
    variants.append(DescVariant(
        strategy="value_prop",
        text=(
            f"<p><strong>What it does:</strong> {summary}</p>"
            f"<p><strong>Why it matters:</strong> Designed to "
            f"deliver {benefit}, this {noun.lower()} stands "
            "apart from generic alternatives.</p>"
            "<p><strong>Bottom line:</strong> If you've tried "
            "other options and been let down, this one "
            "delivers.</p>"
        ),
    ))

    # Social proof: testimonial framing
    variants.append(DescVariant(
        strategy="social_proof",
        text=(
            f"<p><em>\"I've tried a lot of {noun.lower()}s, "
            "and this one is different.\"</em> "
            "— Recent customer review</p>"
            f"<p>{summary}</p>"
            "<p><strong>What customers say:</strong> Real "
            "results, exceeded expectations, would buy "
            "again. Read the reviews and see for yourself.</p>"
        ),
    ))

    return variants


def price_variants(
    *, current_price: float,
) -> list[PriceVariant]:
    """Generate 3 price test points.

    - current: baseline (control)
    - discount_10: -10% off (price-sensitive segment)
    - premium_15: +15% (anchor/premium positioning test)

    Round to .99 endings (common psychological pricing).
    """
    if current_price <= 0:
        return []

    def _round_99(p: float) -> float:
        whole = int(p)
        return round(whole + 0.99, 2)

    variants: list[PriceVariant] = []
    variants.append(PriceVariant(
        label="current",
        price=round(current_price, 2),
    ))
    variants.append(PriceVariant(
        label="discount_10",
        price=_round_99(current_price * 0.9),
    ))
    variants.append(PriceVariant(
        label="premium_15",
        price=_round_99(current_price * 1.15),
    ))
    return variants
