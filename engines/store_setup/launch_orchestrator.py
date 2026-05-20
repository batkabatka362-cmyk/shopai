"""Single-command autonomous store launch.

Bundles every per-capability generator + applier in this
package so an operator can run a SINGLE command to take a
fresh Shopify store from "credentials configured" to
"launchable + earning revenue" with no manual paste required.

Fan-out (8 steps):

  1. Legal policies (refund / privacy / terms / shipping / contact)
  2. Standard pages (About / Contact / FAQ / Shipping & Returns)
  3. Welcome discount code (WELCOME{N})
  4. Starter collections (niche-aware)
  5. Brand assets (logo / favicon / hero / og_image)
  6. Product descriptions (HTML body for empty PDPs)
  7. Product SEO meta (title_tag + meta_description)
  8. (future) homepage hero / shipping zones / email templates

Each step is independently wrapped so a failure in one
doesn't poison the others. ``ready_to_launch`` is True only
when every REQUIRED step succeeded with ``applied_count > 0``.
Optional steps (brand assets, product enrichers) only run
when their inputs are supplied.

Workflow::

    from engines.store_setup.launch_orchestrator import launch_store

    result = launch_store(
        store_name="Acme Beauty",
        niche="beauty",
        region="us",
        founder_name="Jane Doe",
        # Optional brand assets (skipped if not provided)
        logo_url="https://...",
        favicon_url="https://...",
        # Optional product enrichment (skipped if not provided)
        products=fetched_products,
    )

Records via Pattern Z at the orchestrator level too -- one
rolled-up writeback per launch_store call so the autonomous
learning loop sees the launch as ONE logical action even
though the fan-out also records itself.
"""
from __future__ import annotations

import logging
from typing import Any

from engines._writeback_recorder import record_writeback

logger = logging.getLogger(__name__)


# Required steps -- their applied_count must be > 0 for
# ready_to_launch=True. Optional steps only contribute to
# completion when their inputs are supplied.
_REQUIRED_STEPS: frozenset[str] = frozenset({
    "policies", "pages",
})


def launch_store(
    *,
    store_name: str,
    niche: str = "general",
    region: str = "us",
    founder_name: str | None = None,
    store_id: str | None = None,
    include_legal_notice: bool = False,
    include_subscription_policy: bool = False,
    # Welcome discount (always attempted; takes 0 inputs)
    enable_welcome_discount: bool = True,
    # Collections (always attempted; niche-aware defaults)
    enable_collections: bool = True,
    # Brand assets -- skipped when no URLs provided
    logo_url: str | None = None,
    favicon_url: str | None = None,
    hero_url: str | None = None,
    og_image_url: str | None = None,
    # Product enrichment -- skipped when no products provided
    products: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run the autonomous setup steps and return a checklist.

    Args:
        store_name: Store display name. Empty -> early exit.
        niche: Lowercase niche key.
        region: Lowercase region code (us / eu / uk / ...).
        founder_name: Optional founder name for About page.
        store_id: Optional per-store Pattern Z scope.
        include_legal_notice: Add EU-style Impressum policy.
        include_subscription_policy: Add subscription policy.
        enable_welcome_discount: Mint launch promo code.
        enable_collections: Create starter collections.
        logo_url / favicon_url / hero_url / og_image_url:
            Public HTTPS URLs for brand assets. Brand step is
            skipped when no URLs supplied.
        products: Optional list of products to enrich
            (description + SEO meta). Empty / None -> skip.

    Returns:
        ``{
            "policies":    {...},
            "pages":       {...},
            "discount":    {...},
            "collections": {...},
            "brand":       {...},
            "descriptions":{...},
            "seo":         {...},
            "checklist":   [{step, ok, applied, error}, ...],
            "ready_to_launch": bool,
        }``
    """
    name = (store_name or "").strip()
    if not name:
        return _empty_result("store_name_required")

    # ── Step 1: Legal policies ─────────────────────────────
    policies_result = _run_step_policies(
        name=name, niche=niche, region=region,
        store_id=store_id,
        include_legal_notice=include_legal_notice,
        include_subscription_policy=(
            include_subscription_policy
        ),
    )

    # ── Step 2: Storefront pages ──────────────────────────
    pages_result = _run_step_pages(
        name=name, niche=niche,
        founder_name=founder_name, store_id=store_id,
    )

    # ── Step 3: Welcome discount ──────────────────────────
    discount_result = (
        _run_step_welcome_discount(
            name=name, niche=niche, store_id=store_id,
        )
        if enable_welcome_discount
        else _skipped_step("disabled")
    )

    # ── Step 4: Starter collections ───────────────────────
    collections_result = (
        _run_step_collections(
            niche=niche, store_id=store_id,
        )
        if enable_collections
        else _skipped_step("disabled")
    )

    # ── Step 5: Brand assets ──────────────────────────────
    has_brand_urls = any([
        logo_url, favicon_url, hero_url, og_image_url,
    ])
    brand_result = (
        _run_step_brand(
            name=name,
            logo_url=logo_url, favicon_url=favicon_url,
            hero_url=hero_url, og_image_url=og_image_url,
            store_id=store_id,
        )
        if has_brand_urls
        else _skipped_step("no_brand_urls_provided")
    )

    # ── Step 6 + 7: Product enrichment ────────────────────
    if products:
        descriptions_result = _run_step_descriptions(
            products=products, niche=niche,
            store_id=store_id,
        )
        seo_result = _run_step_seo(
            products=products, niche=niche, name=name,
            store_id=store_id,
        )
    else:
        descriptions_result = _skipped_step("no_products")
        seo_result = _skipped_step("no_products")

    # ── Checklist + readiness ─────────────────────────────
    checklist: list[dict[str, Any]] = [
        _checklist_row("policies", policies_result),
        _checklist_row("pages", pages_result),
        _checklist_row("discount", discount_result),
        _checklist_row("collections", collections_result),
        _checklist_row("brand", brand_result),
        _checklist_row("descriptions", descriptions_result),
        _checklist_row("seo", seo_result),
    ]

    # ready_to_launch: every REQUIRED step succeeded with
    # applied_count > 0. Optional steps that were skipped
    # (e.g. no brand URLs) do NOT block readiness.
    ready_to_launch = all(
        row["ok"] for row in checklist
        if row["step"] in _REQUIRED_STEPS
    )

    out = {
        "policies": policies_result,
        "pages": pages_result,
        "discount": discount_result,
        "collections": collections_result,
        "brand": brand_result,
        "descriptions": descriptions_result,
        "seo": seo_result,
        "checklist": checklist,
        "ready_to_launch": ready_to_launch,
    }

    _record_rollup(
        name=name, niche=niche, region=region,
        store_id=store_id,
        ready_to_launch=ready_to_launch,
        checklist=checklist,
    )
    return out


# ── Per-step wrappers (each fully isolated) ───────────────────


def _run_step_policies(
    *, name: str, niche: str, region: str,
    store_id: str | None,
    include_legal_notice: bool,
    include_subscription_policy: bool,
) -> dict[str, Any]:
    try:
        from engines.store_setup.policy_generator import (
            generate_policies,
        )
        from engines.store_setup.policy_applier import (
            apply_policies,
        )
        policies = generate_policies(
            store_name=name, niche=niche, region=region,
            include_legal_notice=include_legal_notice,
            include_subscription_policy=(
                include_subscription_policy
            ),
        )
        return apply_policies(policies, store_id=store_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug("policies step raised: %s", exc)
        return {
            "applied_count": 0, "results": [],
            "error": str(exc),
        }


def _run_step_pages(
    *, name: str, niche: str,
    founder_name: str | None,
    store_id: str | None,
) -> dict[str, Any]:
    try:
        from engines.store_setup.page_generator import (
            generate_pages,
        )
        from engines.store_setup.page_applier import (
            apply_pages,
        )
        pages = generate_pages(
            store_name=name, niche=niche,
            founder_name=founder_name,
        )
        return apply_pages(pages, store_id=store_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug("pages step raised: %s", exc)
        return {
            "applied_count": 0, "results": [],
            "error": str(exc),
        }


def _run_step_welcome_discount(
    *, name: str, niche: str,
    store_id: str | None,
) -> dict[str, Any]:
    try:
        from engines.store_setup.welcome_discount import (
            apply_welcome_discount, generate_welcome_discount,
        )
        params = generate_welcome_discount(
            store_name=name, niche=niche,
        )
        result = apply_welcome_discount(
            params, store_id=store_id,
        )
        # Normalise to the {applied_count, results} shape
        return {
            "applied_count": 1 if result.get("applied") else 0,
            "results": [result],
            "error": result.get("error"),
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("discount step raised: %s", exc)
        return {
            "applied_count": 0, "results": [],
            "error": str(exc),
        }


def _run_step_collections(
    *, niche: str, store_id: str | None,
) -> dict[str, Any]:
    try:
        from engines.store_setup.collection_seeder import (
            apply_starter_collections,
            generate_starter_collections,
        )
        specs = generate_starter_collections(niche=niche)
        return apply_starter_collections(
            specs, store_id=store_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("collections step raised: %s", exc)
        return {
            "applied_count": 0, "results": [],
            "error": str(exc),
        }


def _run_step_brand(
    *, name: str,
    logo_url: str | None, favicon_url: str | None,
    hero_url: str | None, og_image_url: str | None,
    store_id: str | None,
) -> dict[str, Any]:
    try:
        from engines.store_setup.brand_uploader import (
            upload_brand_assets,
        )
        result = upload_brand_assets(
            store_name=name,
            logo_url=logo_url,
            favicon_url=favicon_url,
            hero_url=hero_url,
            og_image_url=og_image_url,
            store_id=store_id,
        )
        return {
            "applied_count": result.get(
                "uploaded_count", 0,
            ),
            "results": result.get("files", []),
            "error": result.get("error"),
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("brand step raised: %s", exc)
        return {
            "applied_count": 0, "results": [],
            "error": str(exc),
        }


def _run_step_descriptions(
    *, products: list[dict[str, Any]], niche: str,
    store_id: str | None,
) -> dict[str, Any]:
    try:
        from engines.store_setup.product_description_enricher import (
            apply_descriptions, enrich_products,
        )
        out = enrich_products(products, niche=niche)
        return apply_descriptions(
            out.get("generated") or [],
            store_id=store_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("descriptions step raised: %s", exc)
        return {
            "applied_count": 0, "results": [],
            "error": str(exc),
        }


def _run_step_seo(
    *, products: list[dict[str, Any]], niche: str,
    name: str, store_id: str | None,
) -> dict[str, Any]:
    try:
        from engines.store_setup.seo_meta_enricher import (
            apply_seo, enrich_seo,
        )
        out = enrich_seo(
            products, niche=niche, store_name=name,
        )
        return apply_seo(
            out.get("generated") or [],
            store_id=store_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("seo step raised: %s", exc)
        return {
            "applied_count": 0, "results": [],
            "error": str(exc),
        }


# ── Helpers ───────────────────────────────────────────────────


def _skipped_step(reason: str) -> dict[str, Any]:
    return {
        "applied_count": 0,
        "results": [],
        "skipped": True,
        "skip_reason": reason,
    }


def _checklist_row(
    step: str, result: dict[str, Any],
) -> dict[str, Any]:
    applied = int(result.get("applied_count", 0) or 0)
    error = result.get("error")
    skipped = bool(result.get("skipped"))
    if skipped:
        # Skipped steps are not failures -- they count as
        # OK for ready_to_launch (only required steps gate
        # readiness; this function says nothing about
        # required vs optional, the caller filters by
        # _REQUIRED_STEPS).
        ok = True
    else:
        ok = applied > 0 and not error
    return {
        "step": step,
        "ok": ok,
        "applied": applied,
        "error": error,
        "skipped": skipped,
    }


def _empty_result(error: str) -> dict[str, Any]:
    return {
        "policies": {"applied_count": 0, "results": []},
        "pages": {"applied_count": 0, "results": []},
        "discount": {"applied_count": 0, "results": []},
        "collections": {"applied_count": 0, "results": []},
        "brand": {"applied_count": 0, "results": []},
        "descriptions": {"applied_count": 0, "results": []},
        "seo": {"applied_count": 0, "results": []},
        "checklist": [],
        "ready_to_launch": False,
        "error": error,
    }


def _record_rollup(
    *,
    name: str, niche: str, region: str,
    store_id: str | None,
    ready_to_launch: bool,
    checklist: list[dict[str, Any]],
) -> None:
    params: dict[str, Any] = {
        "store_name": name,
        "niche": niche,
        "region": region,
    }
    if store_id:
        params["store_id"] = str(store_id)
    failed_steps = [
        c["step"] for c in checklist if not c["ok"]
    ]
    metrics: dict[str, Any] = {
        "ready_to_launch": ready_to_launch,
        "failed_steps": failed_steps,
    }
    for c in checklist:
        metrics[f"applied_{c['step']}"] = c.get(
            "applied", 0,
        )
    try:
        record_writeback(
            engine="store_setup",
            action_type="launch_store",
            capability="SHOPAI_LAUNCH_STORE",
            params=params,
            success=ready_to_launch,
            error=(
                None if ready_to_launch
                else "; ".join(
                    f"{c['step']}: "
                    f"{c.get('error') or 'no_writes'}"
                    for c in checklist
                    if not c["ok"]
                )
            ),
            metrics=metrics,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "launch_orchestrator rollup recording raised: %s",
            exc,
        )
