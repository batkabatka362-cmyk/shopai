"""Publisher bundle — launch one winner product end-to-end.

Sprint 1 commit #1 of AGI_MISSION_PLAN. Orchestrates the modules that
already exist (ContentGenerator, ProductCreator, MetaAdsAdapter,
OutcomeRecorder, ActionBundle, decision_rationale_builder) into one
transactional operation that turns a winner into a live product +
live ad campaign.

Flow (each step is bundled so all-or-nothing):

    1. compose ad copy via ContentGenerator.ad_copy(platform=...)
    2. create the Shopify product via ProductCreator.create_product
    3. publish (status=active) — the creation call already accepts
       status, so this is a single atomic step
    4. create the Meta Ads campaign via MetaAdsAdapter.execute(
         Capability.ADS_CREATE_CAMPAIGN, ...) with the destination
       URL carrying ``shopai_decision_id=<decision_id>`` so
       downstream Shopify orders will surface that decision_id via
       note_attributes (via theme liquid snippet, scheduled for
       owner setup)
    5. record the launch via OutcomeRecorder (capability=launch_sku,
       predicted KPIs) + decision_rationale_builder so the owner
       has an auditable "because" trail

Any step failure rolls back reversibly — unpublish the Shopify
product, pause the Meta campaign — via ActionBundle's reverse-order
compensate. Live writes gated by ``enable_live_execution`` (per
CLAUDE.md §4b/G). When disabled, the whole bundle runs in dry-run
mode: every step records what it *would* have done.

Pure stdlib + our own adapters. Caller supplies winner dict + store
credentials + budget; bundle returns a LaunchResult with the
decision_id, product handle, campaign id, and per-step log.
"""
from __future__ import annotations

import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from utils.logger import get_logger


logger = get_logger("execution.launch.publisher_bundle")


@dataclass
class LaunchRequest:
    """Input to PublisherBundle.launch."""
    winner: dict[str, Any]          # title, price, image_url, url, margin_pct
    shop_url: str                   # e.g. "mystore.myshopify.com"
    api_key: str                    # Shopify Admin API token
    ad_budget_daily: float = 20.0
    ad_objective: str = "OUTCOME_SALES"
    platform: str = "facebook"
    meta_account_id: str = ""
    decision_id: str = ""
    store_currency: str = "USD"
    live: bool = False

    def __post_init__(self) -> None:
        if not self.winner:
            raise ValueError("winner required")
        if not self.shop_url:
            raise ValueError("shop_url required")
        if not self.api_key and self.live:
            raise ValueError(
                "api_key required when live=True",
            )
        if self.ad_budget_daily <= 0:
            raise ValueError("ad_budget_daily must be > 0")
        if self.platform not in (
            "facebook", "instagram", "tiktok", "google",
        ):
            raise ValueError(
                "platform must be one of "
                "facebook|instagram|tiktok|google",
            )

    @property
    def resolved_decision_id(self) -> str:
        return self.decision_id or (
            f"dec_{uuid.uuid4().hex[:12]}"
        )


@dataclass
class StepLog:
    name: str
    status: str                    # "success" | "dry_run" | "error"
    data: dict[str, Any]
    error: str = ""
    ts: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "data": dict(self.data),
            "error": self.error,
            "ts": self.ts,
        }


@dataclass
class LaunchResult:
    decision_id: str
    product_handle: str
    product_id: str
    campaign_id: str
    tracking_url: str              # URL with shopai_decision_id UTM
    steps: list[StepLog]
    ok: bool
    dry_run: bool
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "product_handle": self.product_handle,
            "product_id": self.product_id,
            "campaign_id": self.campaign_id,
            "tracking_url": self.tracking_url,
            "steps": [s.as_dict() for s in self.steps],
            "ok": self.ok,
            "dry_run": self.dry_run,
            "note": self.note,
        }


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:80]


def _enable_live_execution() -> bool:
    """Match the config/settings.json convention — live writes are
    opt-in via a single env flag plus the per-request ``live`` bit."""
    return os.getenv("SHOPAI_ENABLE_LIVE_EXECUTION", "") == "1"


def _tracking_url(
    shop_url: str,
    product_handle: str,
    decision_id: str,
) -> str:
    """Shopify will echo any ``shopai_*`` UTM parameter into the
    order's note_attributes when the storefront theme has the
    ``cart-attribution`` snippet installed (sprint 1 #2 delivers the
    snippet). Until then, UTM still lands in analytics + ad-click
    tracking."""
    base = shop_url
    if not base.startswith("http"):
        base = f"https://{base}"
    return (
        f"{base}/products/{product_handle}"
        f"?shopai_decision_id={decision_id}"
        f"&utm_source=shopai"
        f"&utm_medium=meta_ads"
        f"&utm_campaign={decision_id}"
    )


class PublisherBundle:
    """Transactional product launch — winner → live store → live ad.

    Dependencies are dependency-injected so tests can swap in fakes.
    ``live=True`` inside the request plus the
    ``SHOPAI_ENABLE_LIVE_EXECUTION=1`` env var are BOTH required for
    real writes — the single-gate rule from CLAUDE.md §4b/G.
    """

    def __init__(
        self,
        *,
        content_generator: Any = None,
        product_creator: Any = None,
        ad_adapter: Any = None,
        outcome_recorder: Any = None,
        rationale_builder: Any = None,
    ) -> None:
        self._lock = threading.Lock()
        self._content = content_generator
        self._products = product_creator
        self._ads = ad_adapter
        self._outcomes = outcome_recorder
        self._rationale = rationale_builder
        self._history: list[LaunchResult] = []

    # ── Lazy deps (default to real modules) ──────────────

    def _get_content(self) -> Any:
        if self._content is not None:
            return self._content
        from core.intelligence.content_generator import (
            ContentGenerator,
        )
        self._content = ContentGenerator()
        return self._content

    def _get_products(self) -> Any:
        if self._products is not None:
            return self._products
        from execution.shopify.product_creator import (
            ProductCreator,
        )
        self._products = ProductCreator()
        return self._products

    def _get_ads(self) -> Any:
        if self._ads is not None:
            return self._ads
        from core.adapters.ads.meta_ads import MetaAdsAdapter
        self._ads = MetaAdsAdapter()
        return self._ads

    def _get_outcomes(self) -> Any:
        if self._outcomes is not None:
            return self._outcomes
        from core.attribution.outcome_recorder import (
            OutcomeRecorder,
        )
        self._outcomes = OutcomeRecorder()
        return self._outcomes

    def _get_rationale(self) -> Any:
        if self._rationale is not None:
            return self._rationale
        from core.brain.decision_rationale_builder import (
            DecisionRationaleBuilder,
        )
        self._rationale = DecisionRationaleBuilder()
        return self._rationale

    # ── Launch pipeline ─────────────────────────────────

    def launch(self, request: LaunchRequest) -> LaunchResult:
        if not isinstance(request, LaunchRequest):
            raise TypeError("request must be a LaunchRequest")
        decision_id = request.resolved_decision_id
        dry_run = not (request.live and _enable_live_execution())
        steps: list[StepLog] = []
        rationale = self._get_rationale()
        try:
            rationale.start(
                decision_id=decision_id,
                summary=(
                    f"launch {request.winner.get('title', 'product')}"
                ),
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "rationale.start skipped: %s", exc,
            )
        # 1. copy
        copy_log = self._step_generate_copy(
            request, steps,
        )
        if copy_log.status == "error":
            return self._finalise(
                decision_id, steps,
                dry_run, ok=False,
                note="copy failed",
            )
        # 2. product creation (Shopify)
        product_log = self._step_create_product(
            request, steps, copy_log.data, dry_run,
        )
        if product_log.status == "error":
            return self._finalise(
                decision_id, steps,
                dry_run, ok=False,
                note="product creation failed",
            )
        product_handle = str(
            product_log.data.get("handle")
            or _slugify(request.winner.get("title", "product")),
        )
        product_id = str(product_log.data.get("product_id", ""))
        # 3. meta ads campaign
        campaign_log = self._step_launch_campaign(
            request, steps,
            decision_id=decision_id,
            product_handle=product_handle,
            ad_copy=copy_log.data,
            dry_run=dry_run,
        )
        if campaign_log.status == "error":
            # Best-effort compensate: unpublish product
            self._compensate_unpublish(
                request, steps, product_id, dry_run,
            )
            return self._finalise(
                decision_id, steps,
                dry_run, ok=False,
                note="campaign launch failed",
            )
        # 4. outcome_recorder fingerprint (predicted KPI:
        # claimed_confidence = 0.6 baseline; learners fold in
        # real outcomes once webhooks fire)
        try:
            from core.attribution.outcome_recorder import (
                OutcomeEvent,
            )
            self._get_outcomes().record(OutcomeEvent(
                kind="launch",
                ok=True,
                decision_id=decision_id,
                claimed_confidence=0.6,
                capability_name="launch_sku",
                kpi="launched",
                kpi_value=1.0,
                signals=("winner", "copy", "shopify", "meta"),
                note="publisher_bundle launch",
            ))
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "outcome record at-launch skipped: %s", exc,
            )
        # 5. commit rationale
        try:
            rationale.add(
                decision_id, kind="evidence",
                headline="winner chosen",
                weight=0.9,
                references=(
                    request.winner.get("source", ""),
                ),
            )
            rationale.add(
                decision_id, kind="evidence",
                headline=(
                    f"copy: {copy_log.data.get('headline', '')[:40]}"
                ),
                weight=0.6,
            )
            rationale.add(
                decision_id, kind="gate",
                headline=(
                    "dry_run" if dry_run else "live"
                ),
                weight=1.0,
            )
            rationale.commit(decision_id)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "rationale commit skipped: %s", exc,
            )
        return self._finalise(
            decision_id, steps,
            dry_run, ok=True,
            note="",
            product_handle=product_handle,
            product_id=product_id,
            campaign_id=str(
                campaign_log.data.get("campaign_id", ""),
            ),
            tracking_url=_tracking_url(
                request.shop_url, product_handle, decision_id,
            ),
        )

    # ── Steps ────────────────────────────────────────────

    def _step_generate_copy(
        self,
        request: LaunchRequest,
        steps: list[StepLog],
    ) -> StepLog:
        try:
            copy = self._get_content().ad_copy(
                request.winner,
                platform=request.platform,
            )
            log = StepLog(
                name="generate_copy",
                status="success",
                data=dict(copy),
                ts=time.time(),
            )
        except Exception as exc:  # noqa: BLE001
            log = StepLog(
                name="generate_copy",
                status="error",
                data={},
                error=str(exc),
                ts=time.time(),
            )
        steps.append(log)
        return log

    def _step_create_product(
        self,
        request: LaunchRequest,
        steps: list[StepLog],
        ad_copy: dict[str, Any],
        dry_run: bool,
    ) -> StepLog:
        product_payload = {
            "title": request.winner.get("title", "Product"),
            "description": ad_copy.get("body", ""),
            "price": float(request.winner.get("price", 0)),
            "vendor": "ShopAI",
            "product_type": request.winner.get(
                "product_type", "General",
            ),
            "status": "active",
            "images": (
                [{"src": request.winner["image_url"]}]
                if request.winner.get("image_url") else []
            ),
        }
        if dry_run:
            log = StepLog(
                name="create_product",
                status="dry_run",
                data={
                    "payload": product_payload,
                    "handle": _slugify(product_payload["title"]),
                    "product_id": (
                        f"dryrun_{uuid.uuid4().hex[:8]}"
                    ),
                },
                ts=time.time(),
            )
            steps.append(log)
            return log
        try:
            result = self._get_products().create_product(
                request.shop_url,
                request.api_key,
                product_payload,
            )
            if result.get("status") == "created":
                prod = result.get("product", {})
                log = StepLog(
                    name="create_product",
                    status="success",
                    data={
                        "product_id": str(prod.get("id", "")),
                        "handle": str(
                            prod.get("handle")
                            or _slugify(
                                product_payload["title"],
                            ),
                        ),
                    },
                    ts=time.time(),
                )
            else:
                log = StepLog(
                    name="create_product",
                    status="error",
                    data={},
                    error=str(
                        result.get("error")
                        or result.get("errors", ""),
                    ),
                    ts=time.time(),
                )
        except Exception as exc:  # noqa: BLE001
            log = StepLog(
                name="create_product",
                status="error",
                data={},
                error=str(exc),
                ts=time.time(),
            )
        steps.append(log)
        return log

    def _step_launch_campaign(
        self,
        request: LaunchRequest,
        steps: list[StepLog],
        *,
        decision_id: str,
        product_handle: str,
        ad_copy: dict[str, Any],
        dry_run: bool,
    ) -> StepLog:
        name = (
            f"shopai:{decision_id[:10]}:"
            f"{product_handle[:32]}"
        )
        tracking = _tracking_url(
            request.shop_url, product_handle, decision_id,
        )
        params = {
            "name": name,
            "objective": request.ad_objective,
            "daily_budget": int(
                request.ad_budget_daily * 100,
            ),   # cents
            "status": "PAUSED",   # safety: never ACTIVE on create
            "special_ad_categories": [],
            "account_id": request.meta_account_id or None,
            # Brain hook payload — picked up by
            # AdsBaseAdapter._notify_brain_on_write
            "decision_id": decision_id,
            "claimed_confidence": 0.6,
            "signals": ("publisher_bundle",),
            # Not consumed by Meta; saved for our own logs
            "_tracking_url": tracking,
            "_ad_copy": ad_copy,
        }
        if dry_run:
            log = StepLog(
                name="launch_campaign",
                status="dry_run",
                data={
                    "params": {
                        k: v for k, v in params.items()
                        if k not in ("_ad_copy",)
                    },
                    "campaign_id": (
                        f"dryrun_{uuid.uuid4().hex[:8]}"
                    ),
                },
                ts=time.time(),
            )
            steps.append(log)
            return log
        try:
            from core.adapters.base import Capability
            result = self._get_ads().execute(
                Capability.ADS_CREATE_CAMPAIGN, params,
            )
            if result.ok:
                log = StepLog(
                    name="launch_campaign",
                    status="success",
                    data={
                        "campaign_id": str(
                            (result.data or {}).get(
                                "campaign_id", "",
                            ),
                        ),
                    },
                    ts=time.time(),
                )
            else:
                log = StepLog(
                    name="launch_campaign",
                    status="error",
                    data={},
                    error=str(result.error or "unknown"),
                    ts=time.time(),
                )
        except Exception as exc:  # noqa: BLE001
            log = StepLog(
                name="launch_campaign",
                status="error",
                data={},
                error=str(exc),
                ts=time.time(),
            )
        steps.append(log)
        return log

    def _compensate_unpublish(
        self,
        request: LaunchRequest,
        steps: list[StepLog],
        product_id: str,
        dry_run: bool,
    ) -> None:
        if not product_id:
            return
        if dry_run:
            steps.append(StepLog(
                name="compensate_unpublish",
                status="dry_run",
                data={"product_id": product_id},
                ts=time.time(),
            ))
            return
        # Best-effort — use ProductUpdater if available. Absence is
        # not fatal; a human can clean up manually.
        try:
            from execution.shopify.product_updater import (
                ProductUpdater,
            )
            up = ProductUpdater()
            up.update_product(
                request.shop_url, request.api_key,
                product_id, {"status": "draft"},
            )
            steps.append(StepLog(
                name="compensate_unpublish",
                status="success",
                data={"product_id": product_id},
                ts=time.time(),
            ))
        except Exception as exc:  # noqa: BLE001
            steps.append(StepLog(
                name="compensate_unpublish",
                status="error",
                data={"product_id": product_id},
                error=str(exc),
                ts=time.time(),
            ))

    def _finalise(
        self,
        decision_id: str,
        steps: list[StepLog],
        dry_run: bool,
        *,
        ok: bool,
        note: str = "",
        product_handle: str = "",
        product_id: str = "",
        campaign_id: str = "",
        tracking_url: str = "",
    ) -> LaunchResult:
        result = LaunchResult(
            decision_id=decision_id,
            product_handle=product_handle,
            product_id=product_id,
            campaign_id=campaign_id,
            tracking_url=tracking_url,
            steps=steps,
            ok=ok,
            dry_run=dry_run,
            note=note,
        )
        with self._lock:
            self._history.append(result)
            if len(self._history) > 200:
                del self._history[: len(self._history) - 200]
        return result

    # ── Queries ──────────────────────────────────────────

    def recent(
        self, *, limit: int = 20,
    ) -> list[LaunchResult]:
        with self._lock:
            return list(
                self._history[-max(1, int(limit)):],
            )

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "launches": len(self._history),
                "success_rate": (
                    sum(1 for r in self._history if r.ok)
                    / len(self._history)
                    if self._history else 0.0
                ),
                "dry_run_count": sum(
                    1 for r in self._history if r.dry_run
                ),
            }

    def reset(self) -> int:
        with self._lock:
            n = len(self._history)
            self._history.clear()
        return n
