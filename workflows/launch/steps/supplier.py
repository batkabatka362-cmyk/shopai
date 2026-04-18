"""Step 2 — Supplier wiring.

Once the source is resolved, register the SKU with a supplier-sync
service so Shopify orders auto-flow into fulfillment. ShopAI ships a
CJ Dropshipping adapter today (``core/adapters/sourcing/cj_dropshipping``);
AutoDS adapter is on the roadmap.

The step is optional — manual fulfillment is fine to start.
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

        if not context.source.get("supplier_url"):
            raise StepSkip("source step did not resolve a supplier_url")

        # TODO(brain): when CJ adapter exposes register_sku() / sync_inventory(),
        # call it here and return the supplier_sku id + sync handle.
        raise StepSkip(
            "supplier register_sku not implemented "
            "(adapter present at core/adapters/sourcing/cj_dropshipping.py)"
        )
