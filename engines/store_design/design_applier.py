"""Store Design Engine -- safe Shopify theme applier.

Bridges the engine's recommendations into ACTUAL Shopify
theme file writes. The previous gap: the engine produced text
recommendations but nothing pushed back to Shopify, so the
estimated_conversion_lift number was synthetic + the operator
had to manually translate hints into theme edits.

What this applies
-----------------
Two additive files written to the target theme via
``SHOPIFY_UPSERT_THEME_FILES`` (themeFilesUpsert):

  * ``assets/shopai-design-tokens.json`` -- a JSON blob the
    theme (or future Liquid snippets) can read to surface
    the recommended color palette + nav + mobile hints. Read
    by theme developers; ignored by themes that don't include
    it.
  * ``snippets/shopai-design-recommendations.liquid`` -- a
    Liquid snippet that renders the recommendations as HTML
    comments. Safe to include from any theme template
    (``{%% render 'shopai-design-recommendations' %%}``).

Why "safe"
----------
Neither file is required by any existing Shopify theme. We
write NEW files, never overwrite stock theme files like
``layout/theme.liquid`` or ``config/settings_data.json`` --
those rewrites would risk breaking the storefront. Future
PRs that DO want to modify settings_data.json (e.g. push the
color palette to the live theme's color scheme) should add
explicit opt-in guards + a dry-run path.

Records via Pattern Z
---------------------
The apply call routes through ``record_writeback`` so the
write enters Phase 8's learning loop (MemoryIntelligence +
DataArchitecture + LearningLoop). Each apply event is one
recorded action.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from engines._writeback_recorder import record_writeback

logger = logging.getLogger(__name__)


_TOKENS_FILENAME = "assets/shopai-design-tokens.json"
_SNIPPET_FILENAME = (
    "snippets/shopai-design-recommendations.liquid"
)


def apply_design(
    engine_output: dict[str, Any],
    *,
    theme_id: str,
    store_id: str | None = None,
) -> dict[str, Any]:
    """Apply the design recommendations to a theme.

    Args:
        engine_output: The full ``StoreDesignEngine.run()``
            envelope. Failures short-circuit -- nothing is
            written to Shopify.
        theme_id: Shopify GID for the target theme (e.g.
            ``gid://shopify/OnlineStoreTheme/12345``). Caller
            picks which theme (main / unpublished / dev)
            applies the recommendations.
        store_id: Optional store_id for per-store outcome
            scope.

    Returns:
        Result dict with shape::

            {
                "applied": bool,
                "theme_id": str,
                "files_written": list[str],
                "error": str | None,
            }

        ``applied`` is True only when both files upserted
        successfully. A partial write surfaces in ``error``.
    """
    if not isinstance(engine_output, dict):
        return _build_error_result(
            theme_id, "engine_output_not_a_dict",
        )

    if not isinstance(theme_id, str) or not theme_id.strip():
        return _build_error_result(
            theme_id, "theme_id_required",
        )

    theme_id = theme_id.strip()

    if engine_output.get("status") != "success":
        return _build_error_result(
            theme_id,
            "engine_output_not_successful: "
            f"{engine_output.get('error') or 'unknown'}",
        )

    data = engine_output.get("data") or {}
    if not isinstance(data, dict):
        return _build_error_result(
            theme_id, "engine_data_not_a_dict",
        )

    router = _get_router()
    capability = _get_capability_upsert_theme_files()
    if router is None or capability is None:
        result = _build_error_result(
            theme_id, "router_unavailable",
        )
        _record(
            success=False, theme_id=theme_id,
            store_id=store_id, error="router_unavailable",
            files_written=[],
        )
        return result

    tokens_body = _build_tokens_body(data)
    snippet_body = _build_snippet_body(data)

    files = [
        {"filename": _TOKENS_FILENAME, "body": tokens_body},
        {"filename": _SNIPPET_FILENAME, "body": snippet_body},
    ]

    try:
        adapter_result = router.execute(
            capability,
            {"theme_id": theme_id, "files": files},
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "design_applier: router.execute raised: %s", exc,
        )
        result = _build_error_result(
            theme_id, f"adapter_raise: {exc}",
        )
        _record(
            success=False, theme_id=theme_id,
            store_id=store_id, error=str(exc),
            files_written=[],
        )
        return result

    ok = bool(getattr(adapter_result, "ok", False))
    error = getattr(adapter_result, "error", None)
    if not ok:
        result = _build_error_result(
            theme_id, f"adapter_rejected: {error or 'unknown'}",
        )
        _record(
            success=False, theme_id=theme_id,
            store_id=store_id, error=str(error or "rejected"),
            files_written=[],
        )
        return result

    data_payload = getattr(adapter_result, "data", {}) or {}
    upserted_filenames = (
        data_payload.get("filenames") or []
    )
    result = {
        "applied": True,
        "theme_id": theme_id,
        "files_written": list(upserted_filenames),
        "error": None,
    }
    _record(
        success=True, theme_id=theme_id, store_id=store_id,
        error=None,
        files_written=list(upserted_filenames),
    )
    return result


# --- Helpers ---------------------------------------------------


def _build_tokens_body(data: dict[str, Any]) -> str:
    """Generate the JSON tokens body.

    The schema is deliberately flat + stable so theme code
    can ``settings.shopai_tokens`` lookups without surprise:

      {
        "schema_version": 1,
        "color_palette": {...},
        "navigation": {...},
        "layout_recommendations": [...],
        "mobile_optimizations": [...],
        "estimated_conversion_lift": 0.15
      }
    """
    payload = {
        "schema_version": 1,
        "color_palette": data.get("color_palette") or {},
        "navigation": data.get("navigation") or {},
        "layout_recommendations": (
            data.get("layout_recommendations") or []
        ),
        "mobile_optimizations": (
            data.get("mobile_optimizations") or []
        ),
        "estimated_conversion_lift": float(
            data.get("estimated_conversion_lift") or 0.0,
        ),
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def _build_snippet_body(data: dict[str, Any]) -> str:
    """Generate the Liquid snippet body.

    Renders the recommendations as HTML comments so a theme
    including the snippet can see them in DevTools without
    affecting the storefront's appearance. Theme developers
    can later progressively swap the comments for actual
    template logic.
    """
    layout = data.get("layout_recommendations") or []
    palette = data.get("color_palette") or {}
    nav = data.get("navigation") or {}
    mobile = data.get("mobile_optimizations") or []

    lines: list[str] = [
        "{%- comment -%}",
        "ShopAI Design Engine -- recommendations snapshot.",
        "Generated from the latest store_design engine run.",
        "Safe to include from any template:",
        "  {%- raw -%}{% render 'shopai-design-recommendations' %}{%- endraw -%}",
        "{%- endcomment -%}",
        "",
        "<!-- shopai:design-recommendations -->",
    ]

    if palette:
        lines.append("<!-- color palette: -->")
        for k, v in sorted(palette.items()):
            lines.append(f"<!--   {k} = {v} -->")

    if isinstance(nav, dict):
        links = nav.get("primary_links") or []
        if links:
            lines.append("<!-- navigation links: -->")
            for link in links[:10]:
                if not isinstance(link, dict):
                    continue
                label = link.get("label") or "?"
                url = link.get("url") or link.get("handle") or ""
                lines.append(
                    f"<!--   {label} -> {url} -->"
                )

    if layout:
        lines.append("<!-- layout recommendations: -->")
        for rec in layout[:20]:
            if not isinstance(rec, dict):
                continue
            page = rec.get("page") or "?"
            recommendation = rec.get(
                "recommendation",
            ) or "?"
            impact = rec.get("expected_impact") or ""
            line = f"<!--   [{page}] {recommendation}"
            if impact:
                line += f" ({impact})"
            line += " -->"
            lines.append(line)

    if mobile:
        lines.append("<!-- mobile optimizations: -->")
        for opt in mobile[:20]:
            if not isinstance(opt, dict):
                continue
            t = opt.get("type") or opt.get("name") or "?"
            rec = opt.get("recommendation") or ""
            line = f"<!--   {t}"
            if rec:
                line += f": {rec}"
            line += " -->"
            lines.append(line)

    lines.append("<!-- /shopai:design-recommendations -->")
    return "\n".join(lines)


def _build_error_result(
    theme_id: str, error: str,
) -> dict[str, Any]:
    return {
        "applied": False,
        "theme_id": theme_id,
        "files_written": [],
        "error": error,
    }


def _record(
    *, success: bool, theme_id: str,
    store_id: str | None,
    error: str | None,
    files_written: list[str],
) -> None:
    params: dict[str, Any] = {
        "theme_id": theme_id,
        "files": [_TOKENS_FILENAME, _SNIPPET_FILENAME],
    }
    if store_id:
        params["store_id"] = str(store_id)
    metrics = {
        "files_written": len(files_written or []),
        "applier": "design_applier",
    }
    try:
        record_writeback(
            engine="store_design",
            action_type="apply_design_tokens",
            capability="SHOPIFY_UPSERT_THEME_FILES",
            params=params,
            success=bool(success),
            error=error,
            metrics=metrics,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "design_applier record_writeback raised: %s", exc,
        )


def _get_router() -> Any | None:
    try:
        from core.adapters import get_router as _get
        return _get()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "design_applier router import failed: %s", exc,
        )
        return None


def _get_capability_upsert_theme_files() -> Any | None:
    try:
        from core.adapters.base import Capability
        return Capability.SHOPIFY_UPSERT_THEME_FILES
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "design_applier capability resolve failed: %s", exc,
        )
        return None
