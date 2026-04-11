"""International Expansion Engine — localization checker.

Checks translation and localization readiness for target markets.
All analysis is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any

_MARKET_LANGUAGES: dict[str, str] = {
    "US": "en", "UK": "en", "DE": "de", "FR": "fr", "JP": "ja",
    "AU": "en", "CA": "en", "KR": "ko", "BR": "pt", "IN": "hi",
    "MX": "es", "SE": "sv",
}

_TRANSLATABLE_FIELDS = [
    "title", "description", "meta_title", "meta_description",
    "collection_names", "variant_labels", "shipping_policy",
    "return_policy", "size_guide",
]


def check_localization(
    products: list[dict[str, Any]],
    target_markets: list[str],
) -> dict[str, Any]:
    """Check localization readiness for each target market.

    Args:
        products: Product list with text fields.
        target_markets: List of market codes.

    Returns:
        Structured dict with localization gaps per market.
    """
    try:
        items = copy.deepcopy(products)
        gaps: list[dict[str, Any]] = []

        for market in target_markets:
            code = market.upper().strip()
            language = _MARKET_LANGUAGES.get(code, "unknown")
            is_english = language == "en"

            missing: list[str] = []
            if not is_english:
                for field in _TRANSLATABLE_FIELDS:
                    has_translation = False
                    for item in items:
                        translations = item.get("translations", {})
                        lang_block = translations.get(language, {})
                        if lang_block.get(field):
                            has_translation = True
                            break
                    if not has_translation:
                        missing.append(field)

            total_fields = len(_TRANSLATABLE_FIELDS)
            translated_count = total_fields - len(missing)
            readiness = round(translated_count / total_fields, 2) if total_fields > 0 else 1.0

            cultural_notes: list[str] = []
            if code == "JP":
                cultural_notes.append("Use formal/polite Japanese (keigo) for product descriptions")
                cultural_notes.append("Sizes must be converted to JP sizing standards")
            elif code == "DE":
                cultural_notes.append("German legal requirements: Impressum, Widerrufsrecht")
                cultural_notes.append("Prices must include VAT (Mehrwertsteuer)")
            elif code == "FR":
                cultural_notes.append("French consumer law: 14-day withdrawal right mandatory")
            elif code == "KR":
                cultural_notes.append("Korean won pricing should avoid decimals")
                cultural_notes.append("KC certification may be required for certain products")
            elif code == "BR":
                cultural_notes.append("CPF/CNPJ required for Brazilian customers")
                cultural_notes.append("Import duties may apply — transparent pricing recommended")

            gaps.append({
                "market": code,
                "language": language,
                "translation_ready": is_english or len(missing) == 0,
                "missing_fields": missing,
                "cultural_notes": cultural_notes,
                "readiness_pct": readiness if not is_english else 1.0,
            })

        return {"status": "success", "localization_gaps": gaps}
    except Exception as exc:
        return {"status": "error", "localization_gaps": [], "error": f"Localization check failed: {exc}"}
