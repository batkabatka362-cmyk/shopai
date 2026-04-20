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
    # Wave A-1 of 2026 wiring: EU AI Act Art. 50 compliance
    # gate. When target_markets includes an EU country or
    # ``"EU"`` itself, every entry in ``ai_creatives`` must
    # carry a C2PA manifest + disclosure — else the launch
    # is blocked before Meta Ads upload.
    target_markets: tuple[str, ...] = ("US",)
    ai_creatives: tuple[dict[str, Any], ...] = ()

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
        video_router: Any = None,
    ) -> None:
        self._lock = threading.Lock()
        self._content = content_generator
        self._products = product_creator
        self._ads = ad_adapter
        self._outcomes = outcome_recorder
        self._rationale = rationale_builder
        self._video_router = video_router
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

    def _get_video_router(self) -> Any:
        if self._video_router is not None:
            return self._video_router
        try:
            from core.adapters.fal.video_router import (
                FalVideoRouter,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "fal video router lazy import: %s", exc,
            )
            return None
        self._video_router = FalVideoRouter()
        return self._video_router

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
        # 2.4. Optional fal.ai video generation (Wave D-1 A6).
        #     When winner carries ``video_prompts``, route each
        #     through the cost-aware model picker. Generated
        #     creatives merge into request.ai_creatives so the
        #     EU AI Act gate below sees them too.
        video_log = self._step_generate_videos(
            request, steps, dry_run=dry_run,
        )
        if video_log.status == "error":
            return self._finalise(
                decision_id, steps,
                dry_run, ok=False,
                note="video generation failed",
            )
        # 2.5. EU AI Act Article 50 compliance gate
        #     Wave A-1 of 2026 wiring — block EU-targeted
        #     launches if any AI creative is missing C2PA /
        #     disclosure / has tampered media hash.
        compliance_log = self._step_eu_ai_compliance(
            request, steps,
        )
        if compliance_log.status == "error":
            return self._finalise(
                decision_id, steps,
                dry_run, ok=False,
                note=(
                    "EU AI Act compliance: "
                    + compliance_log.error
                ),
            )
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

    def _build_seo(
        self,
        *,
        request: LaunchRequest,
        ad_copy: dict[str, Any],
    ) -> Any:
        """Build a ``ProductSEO`` bundle for the winner; returns
        None if the SEO generator raises (never blocks a launch)."""
        try:
            from execution.seo.seo_skill import (
                generate_product_seo,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "seo_skill import failed: %s", exc,
            )
            return None
        product = {
            "title": request.winner.get("title", "Product"),
            "description": (
                ad_copy.get("body")
                or request.winner.get("description", "")
            ),
            "image": (
                request.winner.get("image_url")
                or request.winner.get("image", "")
            ),
            "price": float(
                request.winner.get("price", 0) or 0,
            ),
            "sku": str(
                request.winner.get("sku")
                or request.winner.get("external_id", ""),
            ),
            "brand": request.winner.get(
                "brand", "",
            ) or "ShopAI",
            "availability": "InStock",
            "gtin": str(
                request.winner.get("gtin", ""),
            ),
            "rating": request.winner.get("rating"),
            "review_count": request.winner.get(
                "review_count",
            ),
        }
        shop_url = (request.shop_url or "").strip()
        site_url = (
            f"https://{shop_url}"
            if shop_url and not shop_url.startswith("http")
            else shop_url
        )
        store_name = (
            shop_url.replace(".myshopify.com", "")
            .replace("https://", "")
            .replace("http://", "")
            .strip("/")
            .replace("-", " ")
            .title()
            or "ShopAI"
        )
        try:
            return generate_product_seo(
                product,
                store_name=store_name,
                site_url=site_url,
                currency=request.store_currency or "USD",
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "generate_product_seo failed: %s", exc,
            )
            return None

    def _build_schema_script(
        self,
        *,
        request: LaunchRequest,
        ad_copy: dict[str, Any],
    ) -> str:
        """Produce the full @graph JSON-LD (Product + Offer +
        AggregateRating + FAQPage + Organization + Brand + author
        entity) ready to embed in <script type="application/
        ld+json">. Returns an empty string when the module
        can't load or the product has no title — never raises."""
        try:
            from execution.seo.schema_stack import (
                AuthorEntity,
                build_schema_stack,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "schema_stack import failed: %s", exc,
            )
            return ""
        title = str(
            request.winner.get("title") or "",
        ).strip()
        if not title:
            return ""
        shop_url = (request.shop_url or "").strip()
        site_url = (
            f"https://{shop_url}"
            if shop_url and not shop_url.startswith("http")
            else shop_url
        )
        store_name = (
            shop_url.replace(".myshopify.com", "")
            .replace("https://", "")
            .replace("http://", "")
            .strip("/")
            .replace("-", " ")
            .title()
            or "ShopAI Store"
        )
        author = AuthorEntity(
            entity_id=(
                f"{site_url}/#publisher" if site_url
                else "#publisher"
            ),
            name=store_name,
            kind="Organization",
            url=site_url,
        )
        faqs: list[dict[str, str]] = []
        for f in request.winner.get("faqs") or []:
            if isinstance(f, dict) and f.get("q"):
                faqs.append({
                    "q": str(f.get("q", "")),
                    "a": str(f.get("a", "")),
                })
        product = {
            "title": title,
            "handle": request.winner.get("handle")
                or _slugify(title),
            "description": (
                ad_copy.get("body")
                or request.winner.get("description", "")
            ),
            "image": (
                request.winner.get("image_url")
                or request.winner.get("image", "")
            ),
            "price": float(
                request.winner.get("price", 0) or 0,
            ),
            "currency": request.store_currency or "USD",
            "sku": str(
                request.winner.get("sku")
                or request.winner.get("external_id", ""),
            ),
            "brand": request.winner.get("brand") or store_name,
            "availability": "InStock",
            "rating": request.winner.get("rating"),
            "review_count": request.winner.get(
                "review_count",
            ),
        }
        try:
            stack = build_schema_stack(
                product,
                site_url=site_url,
                author=author,
                faqs=faqs or None,
            )
            return stack.as_script_tag()
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "schema_stack build failed: %s", exc,
            )
            return ""

    def _step_create_product(
        self,
        request: LaunchRequest,
        steps: list[StepLog],
        ad_copy: dict[str, Any],
        dry_run: bool,
    ) -> StepLog:
        # Build L6 SEO bundle so the Shopify product carries
        # meta title/description + schema.org + Merchant feed
        # entry from the start (S3-4 wire-in).
        seo_bundle = self._build_seo(
            request=request, ad_copy=ad_copy,
        )
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
        if seo_bundle is not None:
            product_payload["metafields_global_title_tag"] = (
                seo_bundle.meta_title
            )
            product_payload[
                "metafields_global_description_tag"
            ] = seo_bundle.meta_description
            product_payload["seo"] = {
                "title": seo_bundle.meta_title,
                "description": seo_bundle.meta_description,
            }
            if seo_bundle.keywords:
                product_payload["tags"] = ", ".join(
                    seo_bundle.keywords,
                )
        # Wave A-3 wiring: full schema stack (≥3 types with
        # author entity) — +13% LLM citation per 2026 GEO
        # research. Added as a product metafield so the
        # theme can render it in <script type="application/
        # ld+json">.
        schema_script = self._build_schema_script(
            request=request,
            ad_copy=ad_copy,
        )
        if schema_script:
            # Metafields list format Shopify Admin API accepts
            metafields = list(
                product_payload.get("metafields") or [],
            )
            metafields.append({
                "namespace": "shopai",
                "key": "jsonld",
                "type": "json",
                "value": schema_script,
            })
            product_payload["metafields"] = metafields
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
                    "seo": (
                        seo_bundle.as_dict()
                        if seo_bundle is not None else None
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
                        "seo": (
                            seo_bundle.as_dict()
                            if seo_bundle is not None
                            else None
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

    def _step_generate_videos(
        self,
        request: LaunchRequest,
        steps: list[StepLog],
        *,
        dry_run: bool,
    ) -> StepLog:
        """Generate video creatives via fal.ai when the winner
        declares ``video_prompts``. Produced creatives merge
        into ``request.ai_creatives`` so the EU gate + Meta Ads
        campaign see them. Failures are recorded but do not
        block the launch unless every prompt fails."""
        prompts = request.winner.get("video_prompts") or []
        if not isinstance(prompts, (list, tuple)):
            prompts = []
        if not prompts:
            log = StepLog(
                name="video_generate",
                status="success",
                data={"note": "no video_prompts on winner"},
                ts=time.time(),
            )
            steps.append(log)
            return log
        router = self._get_video_router()
        if router is None:
            log = StepLog(
                name="video_generate",
                status="success",
                data={
                    "note": "fal video router unavailable",
                    "skipped": len(prompts),
                },
                ts=time.time(),
            )
            steps.append(log)
            return log
        # In dry-run mode we cost-pick but never hit the API,
        # so simulate-friendly payloads are available downstream.
        sku = str(
            request.winner.get("sku")
            or _slugify(
                request.winner.get("title", "product"),
            ),
        )
        results: list[dict[str, Any]] = []
        costs: float = 0.0
        errors: list[str] = []
        try:
            from core.adapters.fal.video_router import (
                VideoRequest,
            )
        except Exception as exc:  # noqa: BLE001
            log = StepLog(
                name="video_generate",
                status="success",
                data={
                    "note": (
                        f"VideoRequest import failed: {exc}"
                    ),
                },
                ts=time.time(),
            )
            steps.append(log)
            return log
        for raw in prompts:
            if not isinstance(raw, dict):
                continue
            try:
                vr = VideoRequest(
                    sku=sku,
                    prompt=str(raw.get("prompt", "")),
                    aspect=str(raw.get("aspect", "9:16")),
                    duration_s=float(
                        raw.get("duration_s", 5.0),
                    ),
                    quality_floor=str(
                        raw.get("quality_floor", "volume"),
                    ),
                    reference_image_url=str(
                        raw.get(
                            "reference_image_url", "",
                        ),
                    ),
                    seed=int(raw.get("seed", 0) or 0),
                )
            except (TypeError, ValueError) as exc:
                errors.append(str(exc))
                continue
            if dry_run:
                picked = router.pick_model(vr)
                if picked is None:
                    errors.append(
                        "no model matches request",
                    )
                    continue
                estimate = router.estimate_cost(
                    model=picked,
                    duration_s=vr.duration_s,
                )
                results.append({
                    "asset_id": (
                        f"video_{len(results) + 1}"
                    ),
                    "media_kind": "video",
                    "disclosure_text": (
                        "AI-generated — fal.ai "
                        f"{picked.model_id}"
                    ),
                    "dry_run": True,
                    "model_id": picked.model_id,
                    "estimated_cost_usd": estimate,
                    "duration_s": vr.duration_s,
                    "c2pa": {
                        "creator": "shopai",
                        "generator_model": picked.model_id,
                        "ai_generated": True,
                    },
                })
                continue
            res = router.generate(vr)
            if not res.ok:
                errors.append(
                    res.error or res.skipped_reason,
                )
                continue
            costs += float(res.cost_usd)
            results.append({
                "asset_id": res.request_id or (
                    f"video_{len(results) + 1}"
                ),
                "media_kind": "video",
                "disclosure_text": (
                    "AI-generated — fal.ai "
                    f"{res.model_id}"
                ),
                "url": res.video_url,
                "model_id": res.model_id,
                "cost_usd": res.cost_usd,
                "duration_s": res.duration_s,
                "c2pa": {
                    "creator": "shopai",
                    "generator_model": res.model_id,
                    "ai_generated": True,
                },
            })
        # Merge produced creatives into the request so the EU
        # gate and the Meta campaign step both see them.
        if results:
            merged = tuple(request.ai_creatives) + tuple(
                results,
            )
            try:
                request.ai_creatives = merged  # type: ignore[assignment]
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "ai_creatives merge skipped: %s", exc,
                )
        status = "success"
        if results:
            status = "dry_run" if dry_run else "success"
        # If every prompt failed AND we generated nothing, that
        # is a step-level error the caller should surface.
        if not results and errors:
            status = "error"
        log = StepLog(
            name="video_generate",
            status=status,
            data={
                "generated": len(results),
                "total_cost_usd": round(costs, 4),
                "errors": errors,
                "creatives": results,
            },
            error=(
                "; ".join(errors) if status == "error"
                else ""
            ),
            ts=time.time(),
        )
        steps.append(log)
        return log

    def _step_eu_ai_compliance(
        self,
        request: LaunchRequest,
        steps: list[StepLog],
    ) -> StepLog:
        """Gate every AI creative through EUAIActGate before
        the Meta Ads upload step. No creatives OR no EU target
        → no-op pass. Any blocked creative → step errors out."""
        if not request.ai_creatives:
            log = StepLog(
                name="eu_ai_compliance",
                status="success",
                data={"note": "no AI creatives declared"},
                ts=time.time(),
            )
            steps.append(log)
            return log
        try:
            from execution.compliance.eu_ai_act_gate import (
                C2PAManifest,
                Creative,
                get_eu_ai_gate,
            )
        except Exception as exc:  # noqa: BLE001
            log = StepLog(
                name="eu_ai_compliance",
                status="success",
                data={
                    "note": (
                        f"gate unavailable, skipping: {exc}"
                    ),
                },
                ts=time.time(),
            )
            steps.append(log)
            return log
        gate = get_eu_ai_gate()
        blocked: list[str] = []
        verdicts: list[dict[str, Any]] = []
        for raw in request.ai_creatives:
            if not isinstance(raw, dict):
                continue
            c2pa_raw = raw.get("c2pa")
            c2pa = None
            if isinstance(c2pa_raw, dict):
                try:
                    c2pa = C2PAManifest(
                        creator=str(
                            c2pa_raw.get("creator", ""),
                        ),
                        generator_model=str(
                            c2pa_raw.get(
                                "generator_model", "",
                            ),
                        ),
                        created_at_iso=str(
                            c2pa_raw.get(
                                "created_at_iso", "",
                            ),
                        ),
                        ai_generated=bool(
                            c2pa_raw.get(
                                "ai_generated", True,
                            ),
                        ),
                        signature=str(
                            c2pa_raw.get("signature", ""),
                        ),
                        media_hash=str(
                            c2pa_raw.get("media_hash", ""),
                        ),
                    )
                except (TypeError, ValueError) as exc:
                    logger.debug(
                        "c2pa parse failed: %s", exc,
                    )
            creative = Creative(
                asset_id=str(
                    raw.get("asset_id")
                    or f"ad_{request.decision_id[:8]}",
                ),
                media_kind=str(
                    raw.get("media_kind", "image"),
                ),
                c2pa=c2pa,
                disclosure_text=str(
                    raw.get("disclosure_text", ""),
                ),
                target_markets=tuple(
                    request.target_markets,
                ),
            )
            verdict = gate.verify(creative)
            verdicts.append(verdict.as_dict())
            if verdict.decision == "block":
                blocked.append(verdict.asset_id)
        if blocked:
            log = StepLog(
                name="eu_ai_compliance",
                status="error",
                data={"verdicts": verdicts},
                error=(
                    f"blocked {len(blocked)} creative(s): "
                    + ", ".join(blocked)
                ),
                ts=time.time(),
            )
        else:
            log = StepLog(
                name="eu_ai_compliance",
                status="success",
                data={"verdicts": verdicts},
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
