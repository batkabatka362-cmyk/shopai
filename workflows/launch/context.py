"""Launch pipeline shared state contracts.

Schema-first per CLAUDE.md §4b.F — every step reads / writes through
these typed structures so mismatches surface at module load instead of
inside Shopify retries.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal

from core.contracts.business_model import BusinessModel, Channel


SourceKind = Literal["alibaba", "spy_url", "manual", "supplier_sku"]


@dataclass
class LaunchGoal:
    """What the owner asks for. The only required input is *one* source
    pointer; everything else has owner-overridable defaults.

    ``business_model`` + ``channel`` locate this launch on the 4×4
    matrix (docs/BUSINESS_MODEL_MATRIX.md). Defaults reproduce Deguar's
    existing cell so every current call site keeps working — those two
    fields are pure metadata today, Phase 2 will use them for
    adapter routing + risk classification."""

    alibaba_url: str | None = None
    spy_url: str | None = None
    supplier_sku: str | None = None
    manual_payload: dict[str, Any] | None = None

    target_price: float | None = None       # USD; if None, AI computes from cost
    margin_floor: float = 0.30              # min 30 % gross margin
    ad_budget_day: float = 20.0             # USD/day Meta Ads
    ad_kill_roas: float = 1.5               # auto-kill threshold
    ad_kill_after_days: int = 3             # only after N days of data

    niche: str = ""                          # optional human label
    copy_tone: Literal["urgent", "friendly", "luxury", "informative"] = "friendly"
    store_id: str = ""                       # which Shopify store to use

    # ── 4×4 matrix placement (Phase 1 — metadata only) ──────
    business_model: BusinessModel = BusinessModel.DROPSHIPPING
    channel: Channel = Channel.PAID_ADS

    def source_kind(self) -> SourceKind:
        if self.alibaba_url:
            return "alibaba"
        if self.spy_url:
            return "spy_url"
        if self.supplier_sku:
            return "supplier_sku"
        return "manual"


@dataclass
class StepResult:
    name: str
    status: Literal["ok", "skipped", "failed"]
    duration_s: float
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class LaunchContext:
    """Mutable shared state passed through every step. Each step adds its
    own keys; never mutate a key another step owns."""

    goal: LaunchGoal
    launch_id: str
    started_at: float = field(default_factory=time.time)

    # Step outputs (populated as pipeline runs)
    prediction: dict[str, Any] = field(default_factory=dict)     # pre-launch
    source: dict[str, Any] = field(default_factory=dict)         # raw scrape
    supplier: dict[str, Any] = field(default_factory=dict)       # CJ/AutoDS
    media: dict[str, Any] = field(default_factory=dict)          # image urls
    content: dict[str, Any] = field(default_factory=dict)        # title/desc/seo
    shopify_product: dict[str, Any] = field(default_factory=dict)  # id + handle
    related: dict[str, Any] = field(default_factory=dict)          # related_product_ids
    creative: dict[str, Any] = field(default_factory=dict)       # ad assets
    ad_campaign: dict[str, Any] = field(default_factory=dict)    # Meta Ads ids
    tracking: dict[str, Any] = field(default_factory=dict)       # pixel + rules
    monitor: dict[str, Any] = field(default_factory=dict)        # daemon hooks

    steps: list[StepResult] = field(default_factory=list)


@dataclass
class LaunchResult:
    launch_id: str
    status: Literal["complete", "partial", "failed", "aborted"]
    duration_s: float
    steps: list[StepResult]
    shopify_product_id: int | None = None
    shopify_handle: str | None = None
    ad_campaign_id: str | None = None
    ad_campaign_url: str | None = None
    failed_step: str | None = None
    failure_reason: str | None = None
    prediction: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "launch_id": self.launch_id,
            "status": self.status,
            "duration_s": round(self.duration_s, 2),
            "shopify_product_id": self.shopify_product_id,
            "shopify_handle": self.shopify_handle,
            "ad_campaign_id": self.ad_campaign_id,
            "ad_campaign_url": self.ad_campaign_url,
            "failed_step": self.failed_step,
            "failure_reason": self.failure_reason,
            "prediction": self.prediction,
            "steps": [
                {
                    "name": s.name,
                    "status": s.status,
                    "duration_s": round(s.duration_s, 3),
                    "error": s.error,
                }
                for s in self.steps
            ],
        }
