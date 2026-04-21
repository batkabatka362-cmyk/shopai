"""Autopilot — full-autonomy chain from winner discovery to active ad.

Per owner direction §4 "only A full autonomy": the autopilot runs
the whole sprint-1 pipeline end-to-end without owner input:

    winner source → WinnerSearcher.search(top_N)
       ↓
    for each top winner (up to ``max_launches``):
       publisher_bundle.launch(winner)
          ↓
       campaign_activator.activate(auto_approve=True)

Each stage is gated through the v33-v38 brain learners (readiness,
constraints, outcome_recorder, rationale), so "autonomy" here
doesn't mean "no safety" — it means the brain gates replace owner
approval by default. Owner can still observe + override after the
fact via ``shopai publications`` / ``shopai activations``.

Live writes require SHOPAI_ENABLE_LIVE_EXECUTION=1 AND
``AutopilotRequest.live=True``. Dry-run is the default.

Pure stdlib orchestration over existing modules. No new external
deps; sources come from the ``WinnerSearcher`` registry, so the
owner chooses which ``WinnerSource`` implementations to include.
"""
from __future__ import annotations

import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable

from utils.logger import get_logger


logger = get_logger("execution.launch.autopilot")


@dataclass
class AutopilotRequest:
    """Input to ``Autopilot.run``.

    ``winner_sources`` is a list of concrete ``WinnerSource``
    instances. Caller wires them (ManualSeedSource,
    PeerStoreObserverSource, etc.) and passes them in.
    """
    shop_url: str
    api_key: str
    winner_sources: list[Any]
    max_launches: int = 1
    ad_budget_daily: float = 20.0
    platform: str = "facebook"
    meta_account_id: str = ""
    top_n: int = 5
    min_margin_pct: float = 0.15
    auto_activate: bool = True
    live: bool = False

    def __post_init__(self) -> None:
        if not self.shop_url:
            raise ValueError("shop_url required")
        if self.live and not self.api_key:
            raise ValueError(
                "api_key required when live=True",
            )
        if self.max_launches < 1:
            raise ValueError("max_launches must be ≥ 1")
        if self.top_n < 1:
            raise ValueError("top_n must be ≥ 1")
        if self.ad_budget_daily <= 0:
            raise ValueError(
                "ad_budget_daily must be > 0",
            )
        if not 0.0 <= self.min_margin_pct < 1.0:
            raise ValueError(
                "min_margin_pct must be in [0, 1)",
            )
        if not self.winner_sources:
            raise ValueError(
                "at least one winner_source required",
            )
        if self.platform not in (
            "facebook", "instagram", "tiktok", "google",
        ):
            raise ValueError(
                "platform must be facebook|instagram|"
                "tiktok|google",
            )


@dataclass
class AutopilotLaunch:
    """Summary of one winner's trip through the pipeline."""
    winner_title: str
    decision_id: str
    publish_verdict: str       # "ok" | "dry_run" | "error"
    activate_verdict: str      # "activated" | "dry_run" | "pending" | "blocked" | "skipped"
    product_id: str = ""
    product_handle: str = ""
    campaign_id: str = ""
    tracking_url: str = ""
    block_reason: str = ""
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "winner_title": self.winner_title,
            "decision_id": self.decision_id,
            "publish_verdict": self.publish_verdict,
            "activate_verdict": self.activate_verdict,
            "product_id": self.product_id,
            "product_handle": self.product_handle,
            "campaign_id": self.campaign_id,
            "tracking_url": self.tracking_url,
            "block_reason": self.block_reason,
            "note": self.note,
        }


@dataclass
class AutopilotRun:
    id: str
    dry_run: bool
    winners_examined: int
    winners_ranked: int
    launches: list[AutopilotLaunch]
    started_ts: float
    ended_ts: float
    note: str = ""

    @property
    def successful_launches(self) -> int:
        return sum(
            1 for l in self.launches
            if l.publish_verdict in ("ok", "dry_run")
            and l.activate_verdict in (
                "activated", "dry_run",
            )
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "dry_run": self.dry_run,
            "winners_examined": self.winners_examined,
            "winners_ranked": self.winners_ranked,
            "launches": [
                l.as_dict() for l in self.launches
            ],
            "successful_launches": self.successful_launches,
            "started_ts": self.started_ts,
            "ended_ts": self.ended_ts,
            "note": self.note,
        }


def _live_enabled() -> bool:
    """Delegates to ``core.system.live_execution`` so every
    write path in ShopAI uses one definition of "live"."""
    from core.system.live_execution import (
        is_live_execution_enabled,
    )
    return is_live_execution_enabled()


def _video_generation_enabled() -> bool:
    """§4b/G paranoid-mode: video generation costs real money
    (fal.ai call per launch), so autopilot only auto-populates
    ``video_prompts`` when the owner explicitly opts in via
    ``SHOPAI_VIDEO_GENERATE=1``. Default is OFF — owner must
    consciously enable. Owner-curated prompts on a candidate
    bypass this gate (they're already explicit intent).
    """
    return os.getenv("SHOPAI_VIDEO_GENERATE", "") == "1"


def _default_video_prompts(winner: Any) -> list[dict[str, Any]]:
    """Build 2 volume-tier fal.ai video prompts per winner —
    deterministic, no LLM cost.  The PublisherBundle video
    step sees these and runs the fal router; cost stays
    inside the SHOPAI_VIDEO_BUDGET_SKU_WEEK_USD cap (default
    $10/wk, 2×5s×$0.07 = $0.70 per cycle).

    Owners who want richer prompts can attach their own
    ``video_prompts`` to a ``ProductCandidate`` — we leave
    non-empty lists untouched via a ``hasattr`` guard on
    the candidate. Auto-generation is opt-in via the
    ``SHOPAI_VIDEO_GENERATE=1`` env gate.
    """
    # Respect owner-curated prompts even when the env gate
    # is off — owner explicitness wins over policy.
    existing = getattr(winner, "video_prompts", None)
    if isinstance(existing, (list, tuple)) and existing:
        return [dict(p) for p in existing if isinstance(p, dict)]
    # Opt-in gate for auto-generation
    if not _video_generation_enabled():
        return []
    title = str(getattr(winner, "title", "") or "product")
    image_url = str(getattr(winner, "image_url", "") or "")
    prompts: list[dict[str, Any]] = [
        {
            "prompt": (
                f"{title} — lifestyle product shot, "
                "vertical composition, warm cinematic lighting"
            ),
            "aspect": "9:16",
            "duration_s": 5.0,
            "quality_floor": "volume",
        },
        {
            "prompt": (
                f"{title} — close-up demonstration, "
                "subtle motion, neutral background"
            ),
            "aspect": "9:16",
            "duration_s": 5.0,
            "quality_floor": "volume",
        },
    ]
    if image_url:
        prompts[0]["reference_image_url"] = image_url
    return prompts


class Autopilot:
    """End-to-end winner → publish → activate orchestrator.

    Dependencies dep-injected. Each owner of an Autopilot can keep
    a single long-lived instance — the history is in-process but
    a daemon loop naturally accumulates it across cycles.
    """

    def __init__(
        self,
        *,
        winner_searcher: Any = None,
        publisher_bundle: Any = None,
        campaign_activator: Any = None,
    ) -> None:
        self._lock = threading.Lock()
        self._searcher = winner_searcher
        self._publisher = publisher_bundle
        self._activator = campaign_activator
        self._history: list[AutopilotRun] = []

    # ── Lazy deps ────────────────────────────────────────

    def _get_searcher(self, sources: list[Any]) -> Any:
        """Searchers need sources provided by the caller, so we
        build a fresh one per run. The injected searcher (if any)
        is used as a seed and sources are added on top."""
        if self._searcher is not None:
            # If an injected searcher is provided, add the new
            # sources on top of it.
            for s in sources:
                self._searcher.register_source(s)
            return self._searcher
        from agents.research.winner_searcher import (
            WinnerSearcher,
        )
        s = WinnerSearcher(sources=sources)
        return s

    def _get_publisher(self) -> Any:
        if self._publisher is not None:
            return self._publisher
        from execution.launch.publisher_bundle import (
            PublisherBundle,
        )
        self._publisher = PublisherBundle()
        return self._publisher

    def _get_activator(self) -> Any:
        if self._activator is not None:
            return self._activator
        from execution.launch.campaign_activator import (
            CampaignActivator,
        )
        self._activator = CampaignActivator()
        return self._activator

    # ── Main pipeline ────────────────────────────────────

    def run(self, request: AutopilotRequest) -> AutopilotRun:
        if not isinstance(request, AutopilotRequest):
            raise TypeError(
                "request must be AutopilotRequest",
            )
        run_id = f"ap_{uuid.uuid4().hex[:12]}"
        started = time.time()
        dry_run = not (request.live and _live_enabled())
        # 1. discover winners
        searcher = self._get_searcher(
            request.winner_sources,
        )
        # WinnerSearcher min_margin is set at construction; if an
        # injected searcher has a different floor, we honor that.
        search_result = searcher.search(
            top_n=request.top_n,
            publish=False,   # autopilot handles publish itself
        )
        ranked = search_result.ranked[: request.max_launches]
        launches: list[AutopilotLaunch] = []
        for scored in ranked:
            launches.append(
                self._run_one(
                    scored=scored,
                    request=request,
                    dry_run=dry_run,
                ),
            )
        run = AutopilotRun(
            id=run_id,
            dry_run=dry_run,
            winners_examined=search_result.candidates_examined,
            winners_ranked=len(search_result.ranked),
            launches=launches,
            started_ts=started,
            ended_ts=time.time(),
        )
        with self._lock:
            self._history.append(run)
            if len(self._history) > 200:
                del self._history[
                    : len(self._history) - 200
                ]
        return run

    def _run_one(
        self,
        *,
        scored: Any,
        request: AutopilotRequest,
        dry_run: bool,
    ) -> AutopilotLaunch:
        winner = scored.candidate
        winner_dict = {
            "title": winner.title,
            "price": winner.price,
            "cost": winner.cost,
            "image_url": winner.image_url,
            "url": winner.url,
            "source": winner.source,
            "tags": list(winner.tags),
            "external_id": winner.external_id,
            "product_type": (
                winner.tags[0] if winner.tags else ""
            ),
            # A6 wire-through: default 2 volume-tier video
            # prompts per winner so the fal router pipeline
            # actually runs in the daemon. If the candidate
            # already carries ``video_prompts`` (e.g. owner
            # hand-curated) we honour those untouched.
            "video_prompts": _default_video_prompts(winner),
            "sku": winner.external_id,
        }
        # 2. publish (uses publisher_bundle)
        from execution.launch.publisher_bundle import (
            LaunchRequest,
        )
        try:
            publish_req = LaunchRequest(
                winner=winner_dict,
                shop_url=request.shop_url,
                api_key=request.api_key,
                ad_budget_daily=request.ad_budget_daily,
                platform=request.platform,
                meta_account_id=request.meta_account_id,
                live=request.live,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "autopilot publish_req invalid: %s", exc,
            )
            return AutopilotLaunch(
                winner_title=winner.title,
                decision_id="",
                publish_verdict="error",
                activate_verdict="skipped",
                block_reason=str(exc),
                note="publish_request invalid",
            )
        publish_result = self._get_publisher().launch(
            publish_req,
        )
        publish_verdict = (
            "dry_run" if publish_result.dry_run
            else ("ok" if publish_result.ok else "error")
        )
        if not publish_result.ok:
            return AutopilotLaunch(
                winner_title=winner.title,
                decision_id=publish_result.decision_id,
                publish_verdict=publish_verdict,
                activate_verdict="skipped",
                note=publish_result.note,
            )
        # 3. activate (unless owner opts out)
        activate_verdict = "skipped"
        block_reason = ""
        if (
            request.auto_activate
            and publish_result.campaign_id
        ):
            from execution.launch.campaign_activator import (
                ActivateRequest,
            )
            try:
                activate_req = ActivateRequest(
                    campaign_id=(
                        publish_result.campaign_id
                    ),
                    daily_budget_usd=(
                        request.ad_budget_daily
                    ),
                    decision_id=publish_result.decision_id,
                    auto_approve=True,
                    live=request.live,
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "autopilot activate_req invalid: %s",
                    exc,
                )
                activate_verdict = "error"
                block_reason = str(exc)
            else:
                ar = self._get_activator().activate(
                    activate_req,
                )
                activate_verdict = ar.verdict
                if ar.verdict == "blocked":
                    block_reason = ar.block_reason
        return AutopilotLaunch(
            winner_title=winner.title,
            decision_id=publish_result.decision_id,
            publish_verdict=publish_verdict,
            activate_verdict=activate_verdict,
            product_id=publish_result.product_id,
            product_handle=publish_result.product_handle,
            campaign_id=publish_result.campaign_id,
            tracking_url=publish_result.tracking_url,
            block_reason=block_reason,
        )

    # ── Queries ──────────────────────────────────────────

    def recent(
        self, *, limit: int = 20,
    ) -> list[AutopilotRun]:
        with self._lock:
            return list(
                self._history[-max(1, int(limit)):],
            )

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total_runs = len(self._history)
            total_launches = sum(
                len(r.launches) for r in self._history
            )
            successful = sum(
                r.successful_launches for r in self._history
            )
            return {
                "runs": total_runs,
                "total_launches": total_launches,
                "successful_launches": successful,
                "success_rate": (
                    successful / total_launches
                    if total_launches else 0.0
                ),
            }

    def reset(self) -> int:
        with self._lock:
            n = len(self._history)
            self._history.clear()
        return n
