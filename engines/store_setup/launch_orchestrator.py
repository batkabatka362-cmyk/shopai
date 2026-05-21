"""Single-command autonomous store launch.

Bundles the per-capability generators + appliers introduced in
PRs #364 (policies), #365 (pages), #367 (welcome discount),
#370 (starter collections), and #369 (brand assets) so an
operator can run a SINGLE command to take a fresh Shopify
store from "credentials configured" to "launchable" with no
manual paste required.

Workflow::

    from engines.store_setup.launch_orchestrator import (
        launch_store,
    )

    result = launch_store(
        store_name="Acme Beauty",
        niche="beauty",
        region="us",
        founder_name="Jane Doe",
        logo_url="https://example.com/logo.png",
        favicon_url="https://example.com/favicon.png",
    )
    # result = {
    #     "policies":    {applied_count: 5, results: [...]},
    #     "pages":       {applied_count: 4, results: [...]},
    #     "discount":    {applied: True, code: "WELCOME15", ...},
    #     "collections": {applied_count: 4, results: [...]},
    #     "brand":       {uploaded_count: 2, files: [...],
    #                     skipped: False, ok: True},
    #     "checklist": [
    #         {step: "policies",    ok: True, applied: 5},
    #         {step: "pages",       ok: True, applied: 4},
    #         {step: "discount",    ok: True, applied: 1},
    #         {step: "collections", ok: True, applied: 4},
    #         {step: "brand",       ok: True, applied: 2,
    #          skipped: False},
    #     ],
    #     "ready_to_launch": True,
    # }

The brand step is OPTIONAL: when no image URLs are supplied
it's marked ``skipped: True`` and contributes ``ok: True`` to
``ready_to_launch``. A launch without brand assets is still
launchable; assets are polish, not a prerequisite for taking
orders.

Each step is wrapped so a failure in one (policies fail, but
pages still apply) doesn't poison the others. The
``ready_to_launch`` flag is True only when EVERY step
succeeded with applied_count > 0.

Records via Pattern Z at the orchestrator level too -- a
single rolled-up writeback event ``launch_store`` so the
autonomous learning loop sees the launch as one logical
action even though it fans out to dozens of Shopify writes.
"""
from __future__ import annotations

import logging
from typing import Any

from engines._writeback_recorder import record_writeback

logger = logging.getLogger(__name__)


def launch_store(
    *,
    store_name: str,
    niche: str = "general",
    region: str = "us",
    founder_name: str | None = None,
    store_id: str | None = None,
    include_legal_notice: bool = False,
    include_subscription_policy: bool = False,
    logo_url: str | None = None,
    favicon_url: str | None = None,
    hero_url: str | None = None,
    og_image_url: str | None = None,
) -> dict[str, Any]:
    """Run the autonomous setup steps and return a checklist.

    Args:
        store_name: Display name for the store. Empty string
            yields the not-ready early-exit result.
        niche: Lowercase niche key (``beauty``, ``fashion``,
            ``home``, ``tech``, ``food``, ``general``).
        region: Lowercase region code (``us``, ``eu``, ``uk``).
        founder_name: Optional founder name -- threaded into
            the About page if supplied.
        store_id: Optional store_id for per-store recording
            scope on every fan-out call.
        include_legal_notice: Forwarded to policy_generator.
        include_subscription_policy: Forwarded to policy_generator.
        logo_url: Optional public HTTPS URL for the brand logo.
            When ANY of the four image URLs is supplied the
            brand-uploader step runs; when NONE are supplied
            the step is skipped (record as ``skipped``, not
            failed -- a launch without brand assets is still
            launchable, just polish).
        favicon_url: Optional URL for the favicon.
        hero_url: Optional URL for the homepage hero image.
        og_image_url: Optional URL for the social-sharing image.

    Returns:
        ``{policies, pages, discount, collections, brand,
        checklist, ready_to_launch}`` -- see module docstring
        for the schema.
    """
    name = (store_name or "").strip()
    if not name:
        return {
            "policies": {"applied_count": 0, "results": []},
            "pages": {"applied_count": 0, "results": []},
            "discount": {"applied": False, "code": None,
                         "percentage": None,
                         "error": "store_name_required"},
            "collections": {"applied_count": 0, "results": []},
            "brand": {"uploaded_count": 0, "files": [],
                      "missing_assets": [], "ok": False,
                      "skipped": True,
                      "error": "store_name_required"},
            "checklist": [],
            "ready_to_launch": False,
            "error": "store_name_required",
        }

    # ── Step 1: Legal policies ─────────────────────────────
    policies_result: dict[str, Any] = {
        "applied_count": 0, "results": [],
    }
    try:
        from engines.store_setup.policy_generator import (
            generate_policies,
        )
        from engines.store_setup.policy_applier import (
            apply_policies,
        )
        policies = generate_policies(
            store_name=name,
            niche=niche,
            region=region,
            include_legal_notice=include_legal_notice,
            include_subscription_policy=(
                include_subscription_policy
            ),
        )
        policies_result = apply_policies(
            policies, store_id=store_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "launch_orchestrator policy step raised: %s", exc,
        )
        policies_result = {
            "applied_count": 0,
            "results": [],
            "error": str(exc),
        }

    # ── Step 2: Storefront pages ──────────────────────────
    pages_result: dict[str, Any] = {
        "applied_count": 0, "results": [],
    }
    try:
        from engines.store_setup.page_generator import (
            generate_pages,
        )
        from engines.store_setup.page_applier import apply_pages
        pages = generate_pages(
            store_name=name,
            niche=niche,
            founder_name=founder_name,
        )
        pages_result = apply_pages(
            pages, store_id=store_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "launch_orchestrator pages step raised: %s", exc,
        )
        pages_result = {
            "applied_count": 0,
            "results": [],
            "error": str(exc),
        }

    # ── Step 3: Welcome discount ─────────────────────────
    # A launchable storefront with no discount code still
    # technically takes orders, but the standard launch flow
    # creates a WELCOME{N} code so first-time visitors have
    # an incentive to convert. The launch-audit's
    # ``active_discounts`` check needs at least one code; a
    # default-args call here satisfies it.
    discount_result: dict[str, Any] = {
        "applied": False,
        "code": None,
        "percentage": None,
        "error": None,
    }
    try:
        from engines.store_setup.welcome_discount import (
            apply_welcome_discount,
            generate_welcome_discount,
        )
        discount_params = generate_welcome_discount(
            store_name=name,
            niche=niche,
        )
        discount_result = apply_welcome_discount(
            discount_params, store_id=store_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "launch_orchestrator discount step raised: %s", exc,
        )
        discount_result = {
            "applied": False,
            "code": None,
            "percentage": None,
            "error": str(exc),
        }

    # ── Step 4: Starter collections ──────────────────────
    # Niche-aware curated collections give the storefront
    # structure beyond the auto-generated "All" collection.
    # Launch-audit's ``curated_collections`` check expects
    # at least one; the niche-set generators produce 3-5
    # per niche.
    collections_result: dict[str, Any] = {
        "applied_count": 0, "results": [],
    }
    try:
        from engines.store_setup.collection_seeder import (
            apply_starter_collections,
            generate_starter_collections,
        )
        collection_specs = generate_starter_collections(
            niche=niche,
        )
        collections_result = apply_starter_collections(
            collection_specs, store_id=store_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "launch_orchestrator collections step raised: %s",
            exc,
        )
        collections_result = {
            "applied_count": 0,
            "results": [],
            "error": str(exc),
        }

    # ── Step 5: Brand assets (optional) ──────────────────
    # brand_uploader needs operator-supplied image URLs.
    # When NONE of the four are provided, skip the step
    # entirely -- a launch without brand assets is still
    # launchable (the storefront just uses Shopify's default
    # placeholders). When AT LEAST ONE URL is provided, run
    # the uploader; ``ok`` mirrors the uploader's own
    # "logo+favicon both succeeded" contract.
    any_brand_url = any([
        logo_url, favicon_url, hero_url, og_image_url,
    ])
    brand_result: dict[str, Any] = {
        "uploaded_count": 0,
        "files": [],
        "missing_assets": [],
        "ok": True,
        "skipped": True,
        "error": None,
    }
    if any_brand_url:
        try:
            from engines.store_setup.brand_uploader import (
                upload_brand_assets,
            )
            inner = upload_brand_assets(
                store_name=name,
                logo_url=logo_url,
                favicon_url=favicon_url,
                hero_url=hero_url,
                og_image_url=og_image_url,
                store_id=store_id,
            )
            brand_result = {
                "uploaded_count": inner.get("uploaded_count", 0),
                "files": inner.get("files", []),
                "missing_assets": inner.get(
                    "missing_assets", [],
                ),
                "ok": bool(inner.get("ok", False)),
                "skipped": False,
                "error": inner.get("error"),
            }
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "launch_orchestrator brand step raised: %s",
                exc,
            )
            brand_result = {
                "uploaded_count": 0,
                "files": [],
                "missing_assets": [],
                "ok": False,
                "skipped": False,
                "error": str(exc),
            }

    # ── Checklist ────────────────────────────────────────
    checklist: list[dict[str, Any]] = []

    policies_ok = (
        policies_result.get("applied_count", 0) > 0
        and not policies_result.get("error")
    )
    checklist.append({
        "step": "policies",
        "ok": policies_ok,
        "applied": policies_result.get("applied_count", 0),
        "error": policies_result.get("error"),
    })

    pages_ok = (
        pages_result.get("applied_count", 0) > 0
        and not pages_result.get("error")
    )
    checklist.append({
        "step": "pages",
        "ok": pages_ok,
        "applied": pages_result.get("applied_count", 0),
        "error": pages_result.get("error"),
    })

    discount_ok = (
        bool(discount_result.get("applied"))
        and not discount_result.get("error")
    )
    checklist.append({
        "step": "discount",
        "ok": discount_ok,
        "applied": 1 if discount_ok else 0,
        "error": discount_result.get("error"),
    })

    collections_ok = (
        collections_result.get("applied_count", 0) > 0
        and not collections_result.get("error")
    )
    checklist.append({
        "step": "collections",
        "ok": collections_ok,
        "applied": collections_result.get("applied_count", 0),
        "error": collections_result.get("error"),
    })

    # Brand step is "ok" when it was skipped (no URLs given)
    # or when the uploader's own ok flag was True. The whole
    # point of the skip semantics is that absent brand assets
    # don't block ready_to_launch.
    brand_ok = (
        bool(brand_result.get("skipped"))
        or bool(brand_result.get("ok"))
    )
    checklist.append({
        "step": "brand",
        "ok": brand_ok,
        "applied": brand_result.get("uploaded_count", 0),
        "skipped": bool(brand_result.get("skipped")),
        "error": brand_result.get("error"),
    })

    ready_to_launch = bool(
        policies_ok
        and pages_ok
        and discount_ok
        and collections_ok
        and brand_ok
    )

    out = {
        "policies": policies_result,
        "pages": pages_result,
        "discount": discount_result,
        "collections": collections_result,
        "brand": brand_result,
        "checklist": checklist,
        "ready_to_launch": ready_to_launch,
    }

    # ── Pattern Z: rollup recording -----------------------
    # One writeback event per launch_store call so the
    # autonomous learning loop sees the launch as a single
    # logical action even though the fan-out writes also
    # recorded themselves.
    try:
        params: dict[str, Any] = {
            "store_name": name,
            "niche": niche,
            "region": region,
        }
        if store_id:
            params["store_id"] = str(store_id)
        record_writeback(
            engine="store_setup",
            action_type="launch_store",
            capability="SHOPAI_LAUNCH_STORE",
            params=params,
            success=ready_to_launch,
            error=None if ready_to_launch else (
                "; ".join(
                    f"{c['step']}: {c.get('error') or 'no_writes'}"
                    for c in checklist if not c["ok"]
                )
            ),
            metrics={
                "policies_applied": (
                    policies_result.get("applied_count", 0)
                ),
                "pages_applied": (
                    pages_result.get("applied_count", 0)
                ),
                "discount_applied": 1 if discount_ok else 0,
                "collections_applied": (
                    collections_result.get("applied_count", 0)
                ),
                "brand_uploaded": (
                    brand_result.get("uploaded_count", 0)
                ),
                "brand_skipped": bool(
                    brand_result.get("skipped"),
                ),
                "ready_to_launch": ready_to_launch,
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "launch_orchestrator rollup recording raised: %s",
            exc,
        )

    return out
