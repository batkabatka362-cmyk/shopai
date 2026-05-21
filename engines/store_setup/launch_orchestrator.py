"""Single-command autonomous store launch.

Bundles the per-capability generators + appliers introduced in
PRs #364 (policies) and #365 (pages) so an operator can run a
SINGLE command to take a fresh Shopify store from "credentials
configured" to "launchable" with no manual paste required.

Workflow::

    from engines.store_setup.launch_orchestrator import (
        launch_store,
    )

    result = launch_store(
        store_name="Acme Beauty",
        niche="beauty",
        region="us",
        founder_name="Jane Doe",
    )
    # result = {
    #     "policies":    {applied_count: 5, results: [...]},
    #     "pages":       {applied_count: 4, results: [...]},
    #     "discount":    {applied: True, code: "WELCOME10",
    #                     percentage: 10, error: None},
    #     "collections": {applied_count: 4, results: [...]},
    #     "checklist": [
    #         {step: "policies",    ok: True, applied: 5},
    #         {step: "pages",       ok: True, applied: 4},
    #         {step: "discount",    ok: True, applied: 1},
    #         {step: "collections", ok: True, applied: 4},
    #     ],
    #     "ready_to_launch": True,
    # }

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
        logo_url: Optional brand logo URL. When ANY of the
            brand-asset URLs is supplied, Step 5 runs; when
            all are None, the step is skipped (skipped=True,
            doesn't block ready_to_launch).
        favicon_url: Optional brand favicon URL.
        hero_url: Optional hero image URL.
        og_image_url: Optional social-sharing image URL.

    Returns:
        ``{policies, pages, checklist, ready_to_launch}`` --
        see module docstring for the schema.
    """
    name = (store_name or "").strip()
    if not name:
        return {
            "policies": {"applied_count": 0, "results": []},
            "pages": {"applied_count": 0, "results": []},
            "discount": {
                "applied": False, "code": None,
                "percentage": None, "error": None,
            },
            "collections": {
                "applied_count": 0, "results": [],
            },
            "brand": {
                "uploaded_count": 0, "files": [],
                "missing_assets": [], "ok": True,
                "skipped": True, "error": None,
            },
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
    discount_result: dict[str, Any] = {
        "applied": False, "code": None,
        "percentage": None, "error": None,
    }
    try:
        from engines.store_setup.welcome_discount import (
            generate_welcome_discount,
            apply_welcome_discount,
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
            "launch_orchestrator discount step raised: %s",
            exc,
        )
        discount_result = {
            "applied": False, "code": None,
            "percentage": None, "error": str(exc),
        }

    # ── Step 4: Starter collections ──────────────────────
    collections_result: dict[str, Any] = {
        "applied_count": 0, "results": [],
    }
    try:
        from engines.store_setup.collection_seeder import (
            generate_starter_collections,
            apply_starter_collections,
        )
        starter_specs = generate_starter_collections(
            niche=niche,
        )
        collections_result = apply_starter_collections(
            starter_specs, store_id=store_id,
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
    # Only fires when at least one asset URL is supplied. When
    # all are None, the step is SKIPPED -- a no-op rather than
    # a failure. Skipped contributes ok=True to the checklist
    # so omitting brand URLs doesn't block ``ready_to_launch``.
    brand_result: dict[str, Any] = {
        "uploaded_count": 0, "files": [],
        "missing_assets": [], "ok": True,
        "skipped": True, "error": None,
    }
    any_brand_url = any([
        logo_url, favicon_url, hero_url, og_image_url,
    ])
    if any_brand_url:
        try:
            from engines.store_setup.brand_uploader import (
                upload_brand_assets,
            )
            brand_out = upload_brand_assets(
                store_name=name,
                logo_url=logo_url,
                favicon_url=favicon_url,
                hero_url=hero_url,
                og_image_url=og_image_url,
                store_id=store_id,
            )
            brand_result = {
                "uploaded_count": brand_out.get(
                    "uploaded_count", 0,
                ),
                "files": brand_out.get("files") or [],
                "missing_assets": (
                    brand_out.get("missing_assets") or []
                ),
                "ok": bool(brand_out.get("ok")),
                "skipped": False,
                "error": brand_out.get("error"),
            }
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "launch_orchestrator brand step raised: %s",
                exc,
            )
            brand_result = {
                "uploaded_count": 0, "files": [],
                "missing_assets": [],
                "ok": False, "skipped": False,
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

    # Brand: skipped contributes ok=True (no-op, not a failure);
    # attempted-but-failed contributes ok=False.
    brand_skipped = bool(brand_result.get("skipped"))
    brand_ok = (
        brand_skipped
        or (
            bool(brand_result.get("ok"))
            and not brand_result.get("error")
        )
    )
    checklist.append({
        "step": "brand",
        "ok": brand_ok,
        "applied": brand_result.get("uploaded_count", 0),
        "skipped": brand_skipped,
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
                "discount_applied": (
                    1 if discount_result.get("applied")
                    else 0
                ),
                "collections_applied": (
                    collections_result.get(
                        "applied_count", 0,
                    )
                ),
                "brand_uploaded": (
                    brand_result.get("uploaded_count", 0)
                ),
                "brand_skipped": brand_skipped,
                "ready_to_launch": ready_to_launch,
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "launch_orchestrator rollup recording raised: %s",
            exc,
        )

    return out
