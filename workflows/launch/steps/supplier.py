"""Step 2 — Supplier wiring.

Validate the supplier-side SKU exists and record supplier
metadata on the context so the order-fulfillment path later
(core/webhooks/order_handler._dispatch_cj_fulfillment) has the
resolved sourcing_id to place dropship orders against.

CJ Dropshipping's business model doesn't have a "register SKU"
step — orders are placed per-order via create_order. At launch
time the useful thing is to *prove* the sourcing_id resolves
(so we don't discover a typo when an order arrives). This step
does that via the SOURCING_GET_PRODUCT capability.

Optional — manual fulfillment skips cleanly via StepSkip.
"""
from __future__ import annotations

import os
from typing import Any

from ..context import LaunchContext
from ._base import Step, StepSkip


class SupplierStep(Step):
    name = "supplier"
    optional = True

    def execute(self, context: LaunchContext) -> dict[str, Any]:
        if not os.getenv("CJ_DROPSHIPPING_API_KEY") and not os.getenv("AUTODS_API_KEY"):
            raise StepSkip(
                "no supplier API key configured "
                "(set CJ_DROPSHIPPING_API_KEY or AUTODS_API_KEY)"
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

        # AutoDS adapter roadmap — skip cleanly when the user
        # set AUTODS_API_KEY without CJ creds.
        if not os.getenv("CJ_DROPSHIPPING_API_KEY"):
            raise StepSkip(
                "only AUTODS_API_KEY set — AutoDS adapter "
                "pending (tracked in PATH_TO_T2.md)",
            )

        if not sourcing_id:
            # Nothing to validate — record the URL as the best
            # available handle and move on.
            context.supplier = {
                "supplier": "cj_dropshipping",
                "supplier_url": supplier_url,
                "sourcing_id": "",
                "validated": False,
                "reason": (
                    "source gave URL but no sourcing_id; "
                    "validation skipped"
                ),
            }
            return dict(context.supplier)

        from core.adapters.base import Capability
        from core.adapters.sourcing.cj_dropshipping import (
            CJDropshippingAdapter,
        )

        adapter = CJDropshippingAdapter()
        if not adapter.is_configured():
            raise StepSkip(
                "CJ adapter not configured (env present "
                "but adapter rejected)",
            )
        result = adapter.execute(
            Capability.SOURCING_GET_PRODUCT,
            {"sourcing_id": str(sourcing_id)},
        )
        if not result.ok:
            # Don't hard-fail the launch — record the
            # failure + continue. The order-handler retries
            # create_order per-order anyway.
            context.supplier = {
                "supplier": "cj_dropshipping",
                "supplier_url": supplier_url,
                "sourcing_id": str(sourcing_id),
                "validated": False,
                "error": str(
                    getattr(result, "error", "unknown"),
                ),
            }
            return dict(context.supplier)

        product = result.data or {}
        context.supplier = {
            "supplier": "cj_dropshipping",
            "supplier_url": supplier_url,
            "sourcing_id": str(sourcing_id),
            "validated": True,
            "supplier_title": str(
                product.get("title") or "",
            ),
            "supplier_cost_usd": float(
                product.get("price_usd") or 0.0,
            ),
        }
        return dict(context.supplier)
