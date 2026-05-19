"""Push generated legal policies to Shopify via the
``SHOPIFY_UPDATE_SHOP_POLICY`` adapter (PR #363).

Workflow::

    from engines.store_setup.policy_generator import generate_policies
    from engines.store_setup.policy_applier import apply_policies

    policies = generate_policies(
        store_name="Acme Beauty", niche="beauty", region="us",
    )
    result = apply_policies(policies)
    # result = {
    #     "applied_count": 5,
    #     "results": [
    #         {"policy_type": "REFUND_POLICY", "ok": True, ...},
    #         ...
    #     ],
    # }

Each policy is pushed via a separate adapter call so a
failure in one (e.g. a body that's too long for Shopify's
limits) doesn't block the others.

Records via Pattern Z (record_writeback) so every push enters
Phase 8's learning loop.
"""
from __future__ import annotations

import logging
from typing import Any

from engines._writeback_recorder import record_writeback

logger = logging.getLogger(__name__)


def apply_policies(
    policies: dict[str, str],
    *,
    store_id: str | None = None,
) -> dict[str, Any]:
    """Push each generated policy via the shop_policies_write
    adapter.

    Args:
        policies: ``{policy_type: html_body}`` dict from
            :func:`engines.store_setup.policy_generator.generate_policies`.
        store_id: Optional store_id for per-store scope on the
            writeback recorder.

    Returns:
        ``{
            "applied_count": int,
            "results": list[dict],
        }`` -- one dict per attempted policy with shape
        ``{policy_type, ok, error}`` so callers can drill into
        per-policy failures without re-running the apply.
    """
    if not isinstance(policies, dict) or not policies:
        return {"applied_count": 0, "results": []}

    router = _get_router()
    capability = _get_capability()
    if router is None or capability is None:
        results = [
            {
                "policy_type": pt,
                "ok": False,
                "error": "router_unavailable",
            }
            for pt in sorted(policies)
        ]
        for r in results:
            _record(
                policy_type=r["policy_type"],
                success=False,
                store_id=store_id,
                error=r["error"],
            )
        return {"applied_count": 0, "results": results}

    results: list[dict[str, Any]] = []
    applied_count = 0
    for policy_type, body in sorted(policies.items()):
        try:
            adapter_result = router.execute(
                capability,
                {"policy_type": policy_type, "body": body},
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "policy_applier: router.execute raised for %s: %s",
                policy_type, exc,
            )
            results.append({
                "policy_type": policy_type,
                "ok": False,
                "error": f"adapter_raise: {exc}",
            })
            _record(
                policy_type=policy_type, success=False,
                store_id=store_id, error=str(exc),
            )
            continue

        ok = bool(getattr(adapter_result, "ok", False))
        error = getattr(adapter_result, "error", None)
        if ok:
            applied_count += 1
            results.append({
                "policy_type": policy_type,
                "ok": True,
                "error": None,
            })
            _record(
                policy_type=policy_type, success=True,
                store_id=store_id, error=None,
            )
        else:
            results.append({
                "policy_type": policy_type,
                "ok": False,
                "error": str(error or "rejected"),
            })
            _record(
                policy_type=policy_type, success=False,
                store_id=store_id,
                error=str(error or "rejected"),
            )

    return {"applied_count": applied_count, "results": results}


# --- helpers --------------------------------------------------


def _record(
    *,
    policy_type: str,
    success: bool,
    store_id: str | None,
    error: str | None,
) -> None:
    params: dict[str, Any] = {"policy_type": policy_type}
    if store_id:
        params["store_id"] = str(store_id)
    try:
        record_writeback(
            engine="store_setup",
            action_type="apply_shop_policy",
            capability="SHOPIFY_UPDATE_SHOP_POLICY",
            params=params,
            success=bool(success),
            error=error,
            metrics={"policy_type": policy_type},
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "policy_applier record_writeback raised: %s", exc,
        )


def _get_router() -> Any | None:
    try:
        from core.adapters import get_router as _get
        return _get()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "policy_applier router import failed: %s", exc,
        )
        return None


def _get_capability() -> Any | None:
    try:
        from core.adapters.base import Capability
        return Capability.SHOPIFY_UPDATE_SHOP_POLICY
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "policy_applier capability resolve failed: %s", exc,
        )
        return None
