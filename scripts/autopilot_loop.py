"""Autopilot loop daemon — run ShopAI's full pipeline on an interval.

Sprint 2 #4 of AGI_MISSION_PLAN. Turns the one-shot `shopai autopilot`
command into a 24/7 autonomous loop:

    while True:
        autopilot.run() — winner sources → publish → activate
        launch_learner.distill() — episodes → rules → journal
        log a summary line to data/autopilot_loop.log
        sleep(interval)

Respects:
  * compute_budget per-cycle caps (errors cause skip-till-next)
  * SHOPAI_ENABLE_LIVE_EXECUTION + --live double gate
  * graceful shutdown on SIGINT / SIGTERM (finishes current cycle
    then exits)

Usage:
    python scripts/autopilot_loop.py                  # dry-run
    python scripts/autopilot_loop.py --live           # real writes
    python scripts/autopilot_loop.py --interval 600   # 10 min
    python scripts/autopilot_loop.py --iterations 3   # N then stop

Log format (one JSON line per cycle):
    {"ts": ..., "cycle": N, "mode": "dry_run|live",
     "launches": K, "successful": S, "distilled": D,
     "accepted": A, "duration_s": X}

Pure stdlib. Does not poll — sleeps between cycles. Exits cleanly
on KeyboardInterrupt (owner hits Ctrl-C).
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Force sys.path so the daemon works when invoked directly
if __name__ == "__main__":
    _ROOT = Path(__file__).resolve().parent.parent
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from utils.logger import get_logger


logger = get_logger("scripts.autopilot_loop")


_DEFAULT_INTERVAL_S = 900.0   # 15 minutes
_DEFAULT_MAX_ITERATIONS = 0    # 0 = infinite
_DEFAULT_LOG_PATH = Path("data/autopilot_loop.log")


@dataclass
class LoopConfig:
    """Configuration for the autopilot loop."""
    seeds_path: str = "data/winner_seeds.json"
    peers: str = ""
    max_launches: int = 1
    top_n: int = 5
    ad_budget_daily: float = 20.0
    platform: str = "facebook"
    auto_activate: bool = True
    live: bool = False
    interval_s: float = _DEFAULT_INTERVAL_S
    max_iterations: int = _DEFAULT_MAX_ITERATIONS
    log_path: str = str(_DEFAULT_LOG_PATH)
    distill_every: int = 5       # distill every N cycles
    # E-1 GEO: rebuild llms.txt artifacts every N cycles so
    # new launches are discoverable by ChatGPT / Perplexity /
    # Gemini crawlers without a manual CLI run. 0 disables.
    llms_txt_rebuild_every: int = 5
    llms_txt_out_dir: str = "data/llms"
    # Budget allocator — run Thompson plan every N cycles.
    # Hits Meta Ads insights API so we don't spam it per cycle
    # (free tier ~100 calls/hour). 4 cycles × 10-min interval
    # ≈ every 40 min → within Meta rate limits even on a
    # shared ad account. 0 disables.
    budget_plan_every: int = 4

    def __post_init__(self) -> None:
        if self.interval_s <= 0:
            raise ValueError("interval_s must be > 0")
        if self.max_iterations < 0:
            raise ValueError(
                "max_iterations must be ≥ 0",
            )
        if self.max_launches < 1:
            raise ValueError(
                "max_launches must be ≥ 1",
            )
        if self.distill_every < 1:
            raise ValueError(
                "distill_every must be ≥ 1",
            )


@dataclass
class CycleSummary:
    cycle: int
    ts: float
    mode: str                    # "dry_run" | "live"
    launches: int
    successful: int
    distilled_proposals: int
    accepted: int
    duration_s: float
    error: str = ""
    # Phase 2d of 4×4 matrix — count of approval-queue rows
    # auto-expired on this cycle's sweep. Surfaces whether
    # owner is letting HIGH/CRITICAL prompts rot (which would
    # signal Telegram pipeline trouble).
    expired_approvals: int = 0
    # Email campaign engine — count of scheduled flow emails
    # dispatched this cycle (welcome / abandoned-cart /
    # post-purchase / win-back).
    emails_sent: int = 0
    emails_failed: int = 0
    # Win-back daemon sweep — dormant LTV customers enrolled
    # into the win_back flow this cycle. Capped at
    # DEFAULT_MAX_PER_CYCLE to avoid backlog dumps.
    winback_enrolled: int = 0
    # Budget planner — number of SKUs the Thompson allocator
    # produced a plan for this cycle. 0 means either the
    # planner skipped (no budget configured, Meta creds
    # missing) or no matching campaigns exist yet.
    budget_plan_skus: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "cycle": self.cycle,
            "mode": self.mode,
            "launches": self.launches,
            "successful": self.successful,
            "distilled": self.distilled_proposals,
            "accepted": self.accepted,
            "duration_s": round(self.duration_s, 3),
            "expired_approvals": self.expired_approvals,
            "emails_sent": self.emails_sent,
            "emails_failed": self.emails_failed,
            "winback_enrolled": self.winback_enrolled,
            "budget_plan_skus": self.budget_plan_skus,
            "error": self.error,
        }


class AutopilotLoop:
    """Orchestrate repeated autopilot + distill cycles."""

    def __init__(
        self,
        config: LoopConfig,
        *,
        autopilot: Any = None,
        launch_learner: Any = None,
    ) -> None:
        self._config = config
        self._autopilot = autopilot
        self._learner = launch_learner
        self._stop_event = threading.Event()
        self._cycle_count = 0
        self._history: list[CycleSummary] = []
        self._lock = threading.Lock()
        # Log path
        self._log_path = Path(config.log_path)
        self._log_path.parent.mkdir(
            parents=True, exist_ok=True,
        )

    # ── Lazy deps ────────────────────────────────────────

    def _get_autopilot(self) -> Any:
        if self._autopilot is not None:
            return self._autopilot
        from execution.launch.autopilot import Autopilot
        self._autopilot = Autopilot()
        return self._autopilot

    def _get_learner(self) -> Any:
        if self._learner is not None:
            return self._learner
        from agents.learning.launch_learner import (
            LaunchLearner,
        )
        self._learner = LaunchLearner()
        return self._learner

    # ── Control ──────────────────────────────────────────

    def request_stop(self) -> None:
        self._stop_event.set()

    def is_stopping(self) -> bool:
        return self._stop_event.is_set()

    # ── Cycle ────────────────────────────────────────────

    def _build_sources(self) -> list[Any]:
        from agents.research.sources.manual_seed import (
            ManualSeedSource,
        )
        from agents.research.sources.peer_store_observer import (
            PeerStoreObserverSource,
        )
        from agents.research.sources.cj_dropshipping import (
            CJDropshippingSource,
        )
        from agents.research.sources.aliexpress_scraper import (
            AliExpressScraperSource,
        )
        sources: list[Any] = []
        seed_path = (
            Path(self._config.seeds_path)
            if self._config.seeds_path else None
        )
        if seed_path and seed_path.exists():
            sources.append(ManualSeedSource(seed_path))
        peer_list = [
            p.strip()
            for p in self._config.peers.split(",")
            if p.strip()
        ]
        if peer_list:
            sources.append(
                PeerStoreObserverSource(peer_list),
            )
        # CJ auto-enables when creds are in env
        cj = CJDropshippingSource()
        if cj.is_available():
            sources.append(cj)
        # AliExpress only when explicit env opt-in
        ali = AliExpressScraperSource()
        if ali.is_available():
            sources.append(ali)
        return sources

    def _run_one_cycle(self) -> CycleSummary:
        start = time.time()
        with self._lock:
            self._cycle_count += 1
            cycle_id = self._cycle_count
        summary = CycleSummary(
            cycle=cycle_id,
            ts=start,
            mode="live" if self._config.live else "dry_run",
            launches=0,
            successful=0,
            distilled_proposals=0,
            accepted=0,
            duration_s=0.0,
        )
        try:
            sources = self._build_sources()
            if not sources:
                summary.error = (
                    "no winner sources (seeds missing + "
                    "no --peers)"
                )
                summary.duration_s = time.time() - start
                return summary
            shop_url = os.environ.get(
                "SHOPAI_SHOPIFY_URL", "",
            )
            # D1: resolve through the expiring-token auth so
            # public-app stores keep writing past the
            # 2026-04-01 OAuth deadline. Falls through to
            # SHOPAI_SHOPIFY_KEY for legacy custom apps.
            try:
                from core.auth.token_resolver import (
                    resolve_access_token,
                )
                api_key = resolve_access_token(shop_url)
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "token resolver fallback: %s", exc,
                )
                api_key = os.environ.get(
                    "SHOPAI_SHOPIFY_KEY", "",
                )
            meta_account = os.environ.get(
                "META_ADS_ACCOUNT_ID",
                os.environ.get(
                    "meta_ads_account_id", "",
                ),
            )
            from execution.launch.autopilot import (
                AutopilotRequest,
            )
            req = AutopilotRequest(
                shop_url=shop_url,
                api_key=api_key,
                winner_sources=sources,
                max_launches=self._config.max_launches,
                top_n=self._config.top_n,
                ad_budget_daily=(
                    self._config.ad_budget_daily
                ),
                platform=self._config.platform,
                meta_account_id=meta_account,
                auto_activate=self._config.auto_activate,
                live=self._config.live,
            )
            run = self._get_autopilot().run(req)
            summary.launches = len(run.launches)
            summary.successful = run.successful_launches
        except Exception as exc:  # noqa: BLE001
            summary.error = (
                f"autopilot raised: "
                f"{type(exc).__name__}: {exc}"
            )
            logger.warning(
                "autopilot_loop cycle %d raised: %s",
                cycle_id, exc,
            )
            summary.duration_s = time.time() - start
            return summary
        # Distill learning every N cycles
        if (
            cycle_id % self._config.distill_every == 0
        ):
            try:
                report = self._get_learner().distill()
                summary.distilled_proposals = (
                    len(report.proposals)
                )
                summary.accepted = report.accepted
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "autopilot_loop distill failed: %s",
                    exc,
                )
                summary.error = (
                    summary.error or (
                        f"distill raised: {exc}"
                    )
                )
        # E-1 GEO auto-refresh — rebuild llms.txt + markdown
        # mirrors every ``llms_txt_rebuild_every`` cycles so
        # new launches reach LLM crawlers without a manual
        # ``shopai build-llms-txt``. Soft-fail — a rebuild
        # error logs + annotates summary but never aborts the
        # cycle.
        if (
            self._config.llms_txt_rebuild_every > 0
            and cycle_id
            % self._config.llms_txt_rebuild_every == 0
        ):
            try:
                self._rebuild_llms_txt(summary)
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "llms.txt rebuild failed: %s", exc,
                )
                summary.error = (
                    summary.error or (
                        f"llms_txt raised: {exc}"
                    )
                )
        # Phase 2d of 4×4 matrix — sweep expired HIGH/CRITICAL
        # approval rows every cycle so stale pending items
        # don't linger past their TTL and pollute the "pending"
        # view. Soft-fail — queue unavailable (e.g. SQLite
        # lock) logs + annotates but never aborts the cycle.
        try:
            from core.system.approval_queue import get_queue
            summary.expired_approvals = int(
                get_queue().expire_old(),
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "approval queue sweep failed: %s", exc,
            )
            summary.error = (
                summary.error or f"queue_sweep raised: {exc}"
            )
        # Email campaign engine — drain scheduled flow emails
        # whose send_at is in the past. Soft-fail: engine
        # unavailable (missing adapter, disk full, etc.) logs
        # + annotates but never aborts the cycle.
        try:
            from core.engines.email_campaigns import (
                get_engine as _get_email_engine,
            )
            report = _get_email_engine().dispatch_due()
            summary.emails_sent = int(report.sent)
            summary.emails_failed = int(report.failed)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "email dispatch failed: %s", exc,
            )
            summary.error = (
                summary.error
                or f"email_dispatch raised: {exc}"
            )
        # Win-back sweep — enroll up to N dormant LTV
        # customers per cycle into the win_back flow. Skips
        # anyone already in the flow. Soft-fail.
        try:
            from core.engines.budget_buyer import sweep_winback
            wb_report = sweep_winback()
            summary.winback_enrolled = int(
                wb_report.newly_enrolled,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "winback sweep failed: %s", exc,
            )
            summary.error = (
                summary.error
                or f"winback_sweep raised: {exc}"
            )
        # Budget allocator — every N cycles, pull Meta Ads
        # insights + produce a Thompson-sample budget plan.
        # Logs to reports/budget_plans/<ts>.json for owner
        # review. Read-only — doesn't push back to Meta Ads
        # (that's a HIGH risk-gate action handled separately).
        # Soft-fail: no creds / no campaigns / API down all
        # skip cleanly without aborting the cycle.
        if (
            self._config.budget_plan_every > 0
            and cycle_id
            % self._config.budget_plan_every == 0
        ):
            try:
                from core.engines.budget_buyer import (
                    run_budget_plan,
                )
                plan_report = run_budget_plan()
                summary.budget_plan_skus = int(
                    plan_report.skus_planned,
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "budget plan failed: %s", exc,
                )
                summary.error = (
                    summary.error
                    or f"budget_plan raised: {exc}"
                )
        summary.duration_s = time.time() - start
        return summary

    def _rebuild_llms_txt(
        self, summary: "CycleSummary",
    ) -> None:
        """Pull products from the Shopify connector and emit
        llms.txt + llms-full.txt + per-product markdown
        mirrors to disk. No-op when the connector is not
        configured (no store URL / token)."""
        shop_url = os.environ.get(
            "SHOPAI_SHOPIFY_URL", "",
        )
        if not shop_url:
            return
        try:
            from core.bridge.shopify_connector import (
                ShopifyLiveConnector,
            )
            from execution.seo.llms_txt import build_llms_txt
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "llms_txt deps unavailable: %s", exc,
            )
            return
        try:
            data = ShopifyLiveConnector().fetch_store_data()
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "shopify fetch for llms.txt skipped: %s",
                exc,
            )
            return
        products = data.get("products") or []
        if not isinstance(products, list) or not products:
            return
        clean = [
            p for p in products if isinstance(p, dict)
        ]
        if not clean:
            return
        store_name = shop_url.split(".")[0] or "store"
        index = build_llms_txt(
            store_name=store_name,
            store_url=shop_url,
            products=clean,
        )
        out = Path(self._config.llms_txt_out_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "llms.txt").write_text(index.short_txt)
        (out / "llms-full.txt").write_text(index.full_txt)
        mirror_dir = out / "products"
        mirror_dir.mkdir(parents=True, exist_ok=True)
        for existing in mirror_dir.glob("*.md"):
            try:
                existing.unlink()
            except OSError as exc:
                logger.debug(
                    "mirror cleanup: %s", exc,
                )
        for path, body in index.product_mirrors:
            rel = path.lstrip("/")
            if rel.startswith("products/"):
                rel = rel[len("products/"):]
            (mirror_dir / rel).write_text(body)

    def _log_summary(self, summary: CycleSummary) -> None:
        """Append one JSON line to the log file."""
        try:
            with self._log_path.open("a") as fh:
                fh.write(
                    json.dumps(summary.as_dict()) + "\n",
                )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "log append failed: %s", exc,
            )

    # ── Main loop ────────────────────────────────────────

    def run(self) -> list[CycleSummary]:
        """Run cycles until stopped or max_iterations reached.

        Returns the list of per-cycle summaries.
        """
        logger.info(
            "autopilot_loop starting "
            "(interval=%.1fs, live=%s, max=%d)",
            self._config.interval_s,
            self._config.live,
            self._config.max_iterations,
        )
        while not self.is_stopping():
            summary = self._run_one_cycle()
            with self._lock:
                self._history.append(summary)
                if len(self._history) > 500:
                    del self._history[
                        : len(self._history) - 500
                    ]
            self._log_summary(summary)
            logger.info(
                "cycle %d: mode=%s launches=%d "
                "successful=%d distilled=%d "
                "accepted=%d %.2fs %s",
                summary.cycle, summary.mode,
                summary.launches, summary.successful,
                summary.distilled_proposals,
                summary.accepted,
                summary.duration_s,
                f"err={summary.error}"
                if summary.error else "",
            )
            if (
                self._config.max_iterations > 0
                and summary.cycle
                >= self._config.max_iterations
            ):
                logger.info(
                    "max_iterations reached, stopping",
                )
                break
            # Sleep in small chunks so stop flag is responsive
            target = time.time() + self._config.interval_s
            while (
                time.time() < target
                and not self.is_stopping()
            ):
                time.sleep(
                    min(
                        1.0,
                        max(
                            0.0,
                            target - time.time(),
                        ),
                    ),
                )
        logger.info(
            "autopilot_loop stopped after %d cycles",
            self._cycle_count,
        )
        return list(self._history)

    def history(self) -> list[CycleSummary]:
        with self._lock:
            return list(self._history)


# ── CLI entrypoint ─────────────────────────────────────────


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Autopilot loop daemon — recurring "
            "autopilot + distill"
        ),
    )
    p.add_argument(
        "--seeds",
        default="data/winner_seeds.json",
        help="ManualSeedSource JSON file",
    )
    p.add_argument(
        "--peers",
        default="",
        help=(
            "Comma-separated peer Shopify stores "
            "for PeerStoreObserverSource"
        ),
    )
    p.add_argument(
        "--max-launches", type=int, default=1,
    )
    p.add_argument(
        "--top-n", type=int, default=5,
    )
    p.add_argument(
        "--budget", type=float, default=20.0,
    )
    p.add_argument(
        "--platform", default="facebook",
        choices=[
            "facebook", "instagram", "tiktok", "google",
        ],
    )
    p.add_argument(
        "--no-activate", action="store_true",
    )
    p.add_argument(
        "--live", action="store_true",
    )
    p.add_argument(
        "--interval", type=float,
        default=_DEFAULT_INTERVAL_S,
        help="Seconds between cycles (default 900)",
    )
    p.add_argument(
        "--iterations", type=int,
        default=_DEFAULT_MAX_ITERATIONS,
        help=(
            "Max cycles before exiting; 0 = infinite"
        ),
    )
    p.add_argument(
        "--distill-every", type=int, default=5,
    )
    p.add_argument(
        "--log", default=str(_DEFAULT_LOG_PATH),
    )
    return p.parse_args()


def _install_signal_handlers(loop: AutopilotLoop) -> None:
    def _handle(signum, frame):  # noqa: ARG001
        loop.request_stop()
    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)


def main() -> int:
    args = _parse_args()
    try:
        config = LoopConfig(
            seeds_path=args.seeds,
            peers=args.peers,
            max_launches=args.max_launches,
            top_n=args.top_n,
            ad_budget_daily=args.budget,
            platform=args.platform,
            auto_activate=not args.no_activate,
            live=args.live,
            interval_s=args.interval,
            max_iterations=args.iterations,
            log_path=args.log,
            distill_every=args.distill_every,
        )
    except ValueError as exc:
        print(f"[autopilot_loop] {exc}", file=sys.stderr)
        return 2
    loop = AutopilotLoop(config)
    _install_signal_handlers(loop)
    try:
        loop.run()
    except KeyboardInterrupt:
        print("\n[autopilot_loop] interrupted", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
