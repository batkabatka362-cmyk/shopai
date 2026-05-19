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
    #     "policies": {applied_count: 5, results: [...]},
    #     "pages":    {applied_count: 4, results: [...]},
    #     "checklist": [
    #         {step: "policies", ok: True, applied: 5},
    #         {step: "pages",    ok: True, applied: 4},
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

    Returns:
        ``{policies, pages, checklist, ready_to_launch}`` --
        see module docstring for the schema.
    """
    name = (store_name or "").strip()
    if not name:
        return {
            "policies": {"applied_count": 0, "results": []},
            "pages": {"applied_count": 0, "results": []},
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

    ready_to_launch = bool(policies_ok and pages_ok)

    out = {
        "policies": policies_result,
        "pages": pages_result,
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
                "ready_to_launch": ready_to_launch,
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "launch_orchestrator rollup recording raised: %s",
            exc,
        )

    return out
