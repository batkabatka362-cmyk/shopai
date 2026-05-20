"""Niche-aware metaobject definition starter pack.

Shopify metaobjects let stores define custom data types
that themes can reference in Liquid (e.g. ``Author``,
``Recipe``, ``Material``). Each definition has typed
fields the operator fills in once per "row".

Without launch-time definitions, themes have to render
custom content as one-off product description HTML --
which means no reuse across products, no theme-side
filtering, and no structured data downstream.

This module ships **niche-appropriate metaobject
definitions** -- the data types every store in a niche
benefits from:

  * Beauty: Ingredient (name + INCI + benefit + warnings)
  * Fashion: Material (composition + care + origin)
  * Tech: Specification (label + value + unit)
  * Home: Material (name + finish + care)
  * Food: Recipe (ingredients + steps + cuisine)
  * Pets: Ingredient (analysis + source + species_safe_for)
  * Fitness: Exercise (muscle_group + difficulty + rep_range)
  * Jewelry: Stone (type + carat + grade + treatment)
  * Outdoor: TempRating (lower_limit + comfort + season)
  * Baby: Stage (age_range + milestones + safety_notes)
  * General: TeamMember (name + role + bio)

Each definition is ready to feed into
``SHOPIFY_CREATE_METAOBJECT_DEFINITION``. The applier
pushes each per niche + records via Pattern Z.

Return shape from :func:`generate_metaobject_pack`::

    {
        "store_name": "Acme Beauty",
        "niche": "beauty",
        "definitions": [
            {
                "type": "ingredient",
                "name": "Ingredient",
                "description": "...",
                "field_definitions": [
                    {"key": "inci_name", "type":
                     "single_line_text_field",
                     "name": "INCI Name", "required": True},
                    ...
                ],
            },
        ],
    }
"""
from __future__ import annotations

import logging
from typing import Any

from engines._writeback_recorder import record_writeback

logger = logging.getLogger(__name__)


# Niche -> list of metaobject definition specs.
# Field type values per Shopify's metafield-type catalogue.
_NICHE_DEFINITIONS: dict[
    str, list[dict[str, Any]],
] = {
    "beauty": [
        {
            "type": "ingredient",
            "name": "Ingredient",
            "description": (
                "Cosmetic ingredient with INCI name, "
                "benefit, and safety notes."
            ),
            "field_definitions": [
                {
                    "key": "inci_name",
                    "type": "single_line_text_field",
                    "name": "INCI Name",
                    "required": True,
                },
                {
                    "key": "common_name",
                    "type": "single_line_text_field",
                    "name": "Common Name",
                },
                {
                    "key": "benefit",
                    "type": "multi_line_text_field",
                    "name": "Primary Benefit",
                },
                {
                    "key": "safety_notes",
                    "type": "multi_line_text_field",
                    "name": "Safety Notes",
                },
            ],
        },
    ],
    "fashion": [
        {
            "type": "material",
            "name": "Material",
            "description": (
                "Fabric or material with composition, "
                "care, and origin."
            ),
            "field_definitions": [
                {
                    "key": "name",
                    "type": "single_line_text_field",
                    "name": "Material Name",
                    "required": True,
                },
                {
                    "key": "composition",
                    "type": "single_line_text_field",
                    "name": "Composition (e.g. 100% "
                    "cotton)",
                },
                {
                    "key": "care_instructions",
                    "type": "multi_line_text_field",
                    "name": "Care Instructions",
                },
                {
                    "key": "origin",
                    "type": "single_line_text_field",
                    "name": "Origin",
                },
            ],
        },
    ],
    "tech": [
        {
            "type": "specification",
            "name": "Specification",
            "description": (
                "Reusable spec row (label + value + unit) "
                "for product spec sheets."
            ),
            "field_definitions": [
                {
                    "key": "label",
                    "type": "single_line_text_field",
                    "name": "Label",
                    "required": True,
                },
                {
                    "key": "value",
                    "type": "single_line_text_field",
                    "name": "Value",
                    "required": True,
                },
                {
                    "key": "unit",
                    "type": "single_line_text_field",
                    "name": "Unit (optional)",
                },
                {
                    "key": "category",
                    "type": "single_line_text_field",
                    "name": "Category (power / audio / "
                    "battery / ...)",
                },
            ],
        },
    ],
    "home": [
        {
            "type": "material",
            "name": "Material",
            "description": (
                "Material with finish + care for "
                "homewares."
            ),
            "field_definitions": [
                {
                    "key": "name",
                    "type": "single_line_text_field",
                    "name": "Material Name",
                    "required": True,
                },
                {
                    "key": "finish",
                    "type": "single_line_text_field",
                    "name": "Finish",
                },
                {
                    "key": "care_instructions",
                    "type": "multi_line_text_field",
                    "name": "Care Instructions",
                },
                {
                    "key": "indoor_outdoor",
                    "type": "single_line_text_field",
                    "name": "Indoor / Outdoor",
                },
            ],
        },
    ],
    "food": [
        {
            "type": "recipe",
            "name": "Recipe",
            "description": (
                "Linked recipe with ingredients + steps "
                "+ cuisine."
            ),
            "field_definitions": [
                {
                    "key": "title",
                    "type": "single_line_text_field",
                    "name": "Recipe Title",
                    "required": True,
                },
                {
                    "key": "ingredients",
                    "type": "multi_line_text_field",
                    "name": "Ingredients",
                    "required": True,
                },
                {
                    "key": "steps",
                    "type": "multi_line_text_field",
                    "name": "Steps",
                    "required": True,
                },
                {
                    "key": "cuisine",
                    "type": "single_line_text_field",
                    "name": "Cuisine",
                },
                {
                    "key": "prep_minutes",
                    "type": "number_integer",
                    "name": "Prep Time (minutes)",
                },
            ],
        },
    ],
    "pets": [
        {
            "type": "ingredient",
            "name": "Ingredient",
            "description": (
                "Pet-food / treat ingredient with source "
                "+ species safety."
            ),
            "field_definitions": [
                {
                    "key": "name",
                    "type": "single_line_text_field",
                    "name": "Ingredient Name",
                    "required": True,
                },
                {
                    "key": "source",
                    "type": "single_line_text_field",
                    "name": "Source (e.g. UK chicken)",
                },
                {
                    "key": "guaranteed_analysis",
                    "type": "multi_line_text_field",
                    "name": "Guaranteed Analysis",
                },
                {
                    "key": "safe_for_species",
                    "type": "single_line_text_field",
                    "name": "Safe For (dogs / cats / "
                    "both)",
                },
            ],
        },
    ],
    "fitness": [
        {
            "type": "exercise",
            "name": "Exercise",
            "description": (
                "Exercise / training entry with muscle "
                "group + rep guidance."
            ),
            "field_definitions": [
                {
                    "key": "name",
                    "type": "single_line_text_field",
                    "name": "Exercise Name",
                    "required": True,
                },
                {
                    "key": "muscle_group",
                    "type": "single_line_text_field",
                    "name": "Muscle Group",
                },
                {
                    "key": "difficulty",
                    "type": "single_line_text_field",
                    "name": "Difficulty (beginner / "
                    "intermediate / advanced)",
                },
                {
                    "key": "rep_range",
                    "type": "single_line_text_field",
                    "name": "Rep Range",
                },
            ],
        },
    ],
    "jewelry": [
        {
            "type": "stone",
            "name": "Stone",
            "description": (
                "Gemstone entry with type / carat / "
                "grade / treatment."
            ),
            "field_definitions": [
                {
                    "key": "stone_type",
                    "type": "single_line_text_field",
                    "name": "Type (diamond / sapphire / "
                    "...)",
                    "required": True,
                },
                {
                    "key": "carat",
                    "type": "number_decimal",
                    "name": "Carat Weight",
                },
                {
                    "key": "grade",
                    "type": "single_line_text_field",
                    "name": "Grade",
                },
                {
                    "key": "treatment",
                    "type": "single_line_text_field",
                    "name": "Treatment (heat / oil / "
                    "untreated)",
                },
                {
                    "key": "origin",
                    "type": "single_line_text_field",
                    "name": "Origin",
                },
            ],
        },
    ],
    "outdoor": [
        {
            "type": "temp_rating",
            "name": "Temperature Rating",
            "description": (
                "Temperature rating for sleeping bags / "
                "insulation pieces."
            ),
            "field_definitions": [
                {
                    "key": "lower_limit",
                    "type": "number_integer",
                    "name": "Lower Limit (°C)",
                    "required": True,
                },
                {
                    "key": "comfort",
                    "type": "number_integer",
                    "name": "Comfort (°C)",
                },
                {
                    "key": "season",
                    "type": "single_line_text_field",
                    "name": "Season (3-season / 4-season "
                    "/ ...)",
                },
            ],
        },
    ],
    "baby": [
        {
            "type": "stage",
            "name": "Age Stage",
            "description": (
                "Developmental stage with age range + "
                "milestones."
            ),
            "field_definitions": [
                {
                    "key": "label",
                    "type": "single_line_text_field",
                    "name": "Label (0-3mo / 3-6mo / ...)",
                    "required": True,
                },
                {
                    "key": "min_months",
                    "type": "number_integer",
                    "name": "Min Months",
                },
                {
                    "key": "max_months",
                    "type": "number_integer",
                    "name": "Max Months",
                },
                {
                    "key": "milestones",
                    "type": "multi_line_text_field",
                    "name": "Milestones",
                },
                {
                    "key": "safety_notes",
                    "type": "multi_line_text_field",
                    "name": "Safety Notes",
                },
            ],
        },
    ],
    "general": [
        {
            "type": "team_member",
            "name": "Team Member",
            "description": (
                "Reusable team-member profile for "
                "About + Contact pages."
            ),
            "field_definitions": [
                {
                    "key": "name",
                    "type": "single_line_text_field",
                    "name": "Full Name",
                    "required": True,
                },
                {
                    "key": "role",
                    "type": "single_line_text_field",
                    "name": "Role / Title",
                },
                {
                    "key": "bio",
                    "type": "multi_line_text_field",
                    "name": "Bio",
                },
                {
                    "key": "photo_url",
                    "type": "url",
                    "name": "Photo URL",
                },
            ],
        },
    ],
}


def generate_metaobject_pack(
    *,
    store_name: str,
    niche: str = "general",
) -> dict[str, Any]:
    """Build niche-aware metaobject definition specs.

    Args:
        store_name: Display name. Empty -> empty dict.
        niche: Lowercase niche key. Unknown -> general
            (TeamMember only).

    Returns:
        ``{store_name, niche, definitions: [...]}``.
    """
    name = (store_name or "").strip()
    if not name:
        return {}

    niche_n = (niche or "general").strip().lower() or "general"
    raw = _NICHE_DEFINITIONS.get(
        niche_n, _NICHE_DEFINITIONS["general"],
    )

    # Deep-copy each definition so callers can mutate
    # the returned list without poisoning the library.
    definitions: list[dict[str, Any]] = []
    for d in raw:
        definitions.append({
            "type": d["type"],
            "name": d["name"],
            "description": d["description"],
            "field_definitions": [
                dict(fd) for fd in d["field_definitions"]
            ],
        })

    return {
        "store_name": name,
        "niche": niche_n,
        "definitions": definitions,
    }


def apply_metaobject_pack(
    spec: dict[str, Any],
    *,
    store_id: str | None = None,
) -> dict[str, Any]:
    """Push each definition via
    SHOPIFY_CREATE_METAOBJECT_DEFINITION.

    Args:
        spec: Dict from :func:`generate_metaobject_pack`.
        store_id: Optional per-store Pattern Z scope.

    Returns:
        ``{applied_count, results}``. Each result:
        ``{type, ok, error, definition_id}``.
    """
    if not isinstance(spec, dict):
        return {"applied_count": 0, "results": []}
    definitions = spec.get("definitions") or []
    if not isinstance(definitions, list) or not definitions:
        return {"applied_count": 0, "results": []}

    router = _get_router()
    capability = _get_capability()
    if router is None or capability is None:
        results = [
            {
                "type": d.get("type", ""),
                "ok": False,
                "error": "router_unavailable",
                "definition_id": None,
            }
            for d in definitions
        ]
        for r in results:
            _record(
                type_handle=r["type"], success=False,
                error="router_unavailable",
                store_id=store_id,
            )
        return {"applied_count": 0, "results": results}

    results: list[dict[str, Any]] = []
    applied = 0
    for definition in definitions:
        type_handle = definition.get("type", "")
        if not type_handle:
            results.append({
                "type": "",
                "ok": False,
                "error": "missing_type",
                "definition_id": None,
            })
            continue
        try:
            res = router.execute(capability, definition)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "metaobject_definitions raised for %s: %s",
                type_handle, exc,
            )
            results.append({
                "type": type_handle,
                "ok": False,
                "error": f"adapter_raise: {exc}",
                "definition_id": None,
            })
            _record(
                type_handle=type_handle, success=False,
                error=str(exc), store_id=store_id,
            )
            continue
        ok = bool(getattr(res, "ok", False))
        err = getattr(res, "error", None)
        definition_id = None
        if ok:
            data = getattr(res, "data", {}) or {}
            payload = (
                data.get("definition")
                or data.get("metaobject_definition")
                or {}
            )
            definition_id = payload.get("id")
            applied += 1
        results.append({
            "type": type_handle,
            "ok": ok,
            "error": (
                None if ok else str(err or "rejected")
            ),
            "definition_id": definition_id,
        })
        _record(
            type_handle=type_handle, success=ok,
            error=None if ok else str(err or "rejected"),
            store_id=store_id,
        )

    return {"applied_count": applied, "results": results}


# ── Helpers ───────────────────────────────────────────────────


def _record(
    *,
    type_handle: str,
    success: bool,
    error: str | None,
    store_id: str | None,
) -> None:
    params: dict[str, Any] = {"type": type_handle}
    if store_id:
        params["store_id"] = str(store_id)
    try:
        record_writeback(
            engine="store_setup",
            action_type="apply_metaobject_definition",
            capability="SHOPIFY_CREATE_METAOBJECT_DEFINITION",
            params=params,
            success=bool(success),
            error=error,
            metrics={"type": type_handle},
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "metaobject_definitions record_writeback "
            "raised: %s", exc,
        )


def _get_router() -> Any | None:
    try:
        from core.adapters import get_router as _get
        return _get()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "metaobject_definitions router import "
            "failed: %s", exc,
        )
        return None


def _get_capability() -> Any | None:
    try:
        from core.adapters.base import Capability
        return Capability.SHOPIFY_CREATE_METAOBJECT_DEFINITION
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "metaobject_definitions capability resolve "
            "failed: %s", exc,
        )
        return None
