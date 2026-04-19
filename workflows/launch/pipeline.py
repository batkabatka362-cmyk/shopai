"""LaunchPipeline — runs the 9 steps in order, capturing per-step
outcomes and short-circuiting on hard failures.

Hard rules (per CLAUDE.md §4b):
  • Each step is isolated (failure doesn't poison earlier state)
  • Skipped optional steps don't fail the pipeline
  • Every launch_id is recorded in memory for later replay
"""
from __future__ import annotations

import time
import uuid

from utils.logger import get_logger

from .context import LaunchGoal, LaunchContext, LaunchResult
from .steps import (
    SourceStep, SupplierStep, MediaStep, ContentStep,
    ShopifyCreateStep, RelatedProductsStep, CreativeStep,
    AdsLaunchStep, TrackingStep, MonitorStep,
)


logger = get_logger("workflows.launch.pipeline")


# Step name → context attribute. Keeps step output assignment explicit
# so a step can't accidentally clobber another step's slot.
_STEP_SLOT = {
    "source": "source",
    "supplier": "supplier",
    "media": "media",
    "content": "content",
    "shopify_create": "shopify_product",
    "related": "related",
    "creative": "creative",
    "ads_launch": "ad_campaign",
    "tracking": "tracking",
    "monitor": "monitor",
}


# Steps that, if they hard-fail, must abort the pipeline. Optional steps
# (supplier, ads_launch when creds missing) only mark themselves skipped.
_HARD_REQUIRED = {"source", "media", "content", "shopify_create"}


class LaunchPipeline:
    """Executes the 9-step launch flow for a single product.

    The pipeline is stateless — instantiate fresh per launch.
    """

    STEPS = (
        SourceStep,
        SupplierStep,
        MediaStep,
        ContentStep,
        ShopifyCreateStep,
        RelatedProductsStep,
        CreativeStep,
        AdsLaunchStep,
        TrackingStep,
        MonitorStep,
    )

    def run(self, goal: LaunchGoal) -> LaunchResult:
        launch_id = f"launch_{uuid.uuid4().hex[:12]}"
        context = LaunchContext(goal=goal, launch_id=launch_id)
        started = time.monotonic()

        logger.info(
            "Launch %s starting (source_kind=%s, store=%s)",
            launch_id, goal.source_kind(), goal.store_id or "<default>",
        )

        failed_step: str | None = None
        failure_reason: str | None = None

        for step_cls in self.STEPS:
            step = step_cls()
            result = step.run(context)
            context.steps.append(result)

            if result.status == "ok" and result.output:
                slot = _STEP_SLOT.get(step.name)
                if slot:
                    setattr(context, slot, result.output)

            if result.status == "failed" and step.name in _HARD_REQUIRED:
                failed_step = step.name
                failure_reason = result.error
                logger.error(
                    "Launch %s aborted at hard-required step %s: %s",
                    launch_id, step.name, result.error,
                )
                break

        elapsed = time.monotonic() - started
        any_failed = any(s.status == "failed" for s in context.steps)
        any_ok = any(s.status == "ok" for s in context.steps)
        if failed_step:
            status = "failed"
        elif any_failed:
            status = "partial"
        elif any_ok:
            status = "complete"
        else:
            status = "partial"

        return LaunchResult(
            launch_id=launch_id,
            status=status,
            duration_s=elapsed,
            steps=list(context.steps),
            shopify_product_id=context.shopify_product.get("product_id"),
            shopify_handle=context.shopify_product.get("handle"),
            ad_campaign_id=context.ad_campaign.get("campaign_id"),
            ad_campaign_url=context.ad_campaign.get("admin_url"),
            failed_step=failed_step,
            failure_reason=failure_reason,
        )
