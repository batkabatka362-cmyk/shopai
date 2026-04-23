"""Step 2 — Supplier wiring.

Validate the supplier-side SKU exists and record supplier
metadata on the context so the order-fulfillment path later
has the resolved sourcing_id to place dropship orders against.

Picks the right supplier adapter based on which env keys are
set:

  * ``CJ_DROPSHIPPING_EMAIL`` + ``CJ_DROPSHIPPING_PASSWORD``
    → CJ adapter (priority=90, default winner when both
    sourcing backends are configured)
  * ``AUTODS_API_KEY`` → AutoDS adapter (priority=80, paid
    fallback with US warehouse + multi-marketplace sourcing)

When both are configured, CJ wins — owner can override by
passing ``context.source["preferred_supplier"] = "autods"``.
When neither is configured the step skips cleanly.

Neither supplier has a "register SKU" step; orders place
per-order via create_order. At launch time the useful thing
is to *prove* the sourcing_id resolves so we don't discover a
typo once a buyer hits checkout.
"""
from __future__ import annotations

import os
from typing import Any

from ..context import LaunchContext
from ._base import Step, StepSkip


def _cj_configured() -> bool:
    return bool(
        os.getenv("CJ_DROPSHIPPING_EMAIL")
        and os.getenv("CJ_DROPSHIPPING_PASSWORD"),
    )


def _autods_configured() -> bool:
    return bool(os.getenv("AUTODS_API_KEY"))


def _pick_supplier(
    preferred: str, source: dict[str, Any],
) -> str:
    """Return the canonical adapter name to use. Owner override
    via ``source.preferred_supplier`` wins if that adapter is
    actually configured; otherwise fall back to CJ-first,
    AutoDS-second."""
    pref = (preferred or "").strip().lower()
    if pref in ("autods", "auto_ds", "auto-ds") and _autods_configured():
        return "autods"
    if pref in ("cj", "cj_dropshipping") and _cj_configured():
        return "cj_dropshipping"
    if _cj_configured():
        return "cj_dropshipping"
    if _autods_configured():
        return "autods"
    return ""


def _load_adapter(name: str):
    """Lazy import so an AutoDS-only env doesn't pull CJ (and
    vice versa) into memory. Also refreshes the adapter config
    cache so the adapter instance sees current ``os.environ``
    (important when this step runs after env mutations — e.g.
    owner rotating the API key mid-session)."""
    from core.adapters.base import Capability
    from core.adapters.config import get_config
    get_config().reload()
    if name == "cj_dropshipping":
        from core.adapters.sourcing.cj_dropshipping import (
            CJDropshippingAdapter,
        )
        return CJDropshippingAdapter(), Capability
    if name == "autods":
        from core.adapters.sourcing.autods import AutoDSAdapter
        return AutoDSAdapter(), Capability
    raise ValueError(f"unknown supplier: {name}")


class SupplierStep(Step):
    name = "supplier"
    optional = True

    def execute(self, context: LaunchContext) -> dict[str, Any]:
        if not _cj_configured() and not _autods_configured():
            raise StepSkip(
                "no supplier API key configured "
                "(set CJ_DROPSHIPPING_EMAIL+_PASSWORD or "
                "AUTODS_API_KEY)"
            )

        supplier_url = context.source.get("supplier_url") or ""
        sourcing_id = (
            context.source.get("sourcing_id")
            or context.source.get("supplier_sku")
            or ""
        )
        if not supplier_url and not sourcing_id:
            raise StepSkip(
                "source step did not resolve a "
                "supplier_url or sourcing_id",
            )

        preferred = str(
            context.source.get("preferred_supplier") or "",
        )
        supplier_name = _pick_supplier(
            preferred, context.source,
        )
        if not supplier_name:
            raise StepSkip(
                "no configured supplier adapter for this "
                "source (env rejected by both CJ + AutoDS)",
            )

        if not sourcing_id:
            # Nothing to validate — record the URL as the best
            # available handle and move on.
            context.supplier = {
                "supplier": supplier_name,
                "supplier_url": supplier_url,
                "sourcing_id": "",
                "validated": False,
                "reason": (
                    "source gave URL but no sourcing_id; "
                    "validation skipped"
                ),
            }
            return dict(context.supplier)

        adapter, Capability = _load_adapter(supplier_name)
        if not adapter.is_configured():
            raise StepSkip(
                f"{supplier_name} adapter not configured "
                "(env present but adapter rejected)",
            )
        result = adapter.execute(
            Capability.SOURCING_GET_PRODUCT,
            {"sourcing_id": str(sourcing_id)},
        )
        if not result.ok:
            # Don't hard-fail the launch — record the failure
            # + continue. The order-handler retries create_order
            # per-order anyway.
            context.supplier = {
                "supplier": supplier_name,
                "supplier_url": supplier_url,
                "sourcing_id": str(sourcing_id),
                "validated": False,
                "error": str(
                    getattr(result, "error", "unknown"),
                ),
            }
            return dict(context.supplier)

        product = (result.data or {}).get("product") or (
            result.data or {}
        )
        context.supplier = {
            "supplier": supplier_name,
            "supplier_url": supplier_url,
            "sourcing_id": str(sourcing_id),
            "validated": True,
            "supplier_title": str(
                product.get("title") or "",
            ),
            "supplier_cost_usd": float(
                product.get("cost_usd")
                or product.get("price_usd")
                or 0.0,
            ),
        }
        return dict(context.supplier)
