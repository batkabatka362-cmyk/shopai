"""Build the on-ramp guide from current state."""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Stage:
    name: str
    title: str
    cli_command: str
    rationale: str
    status: str = "pending"   # done / next / pending


@dataclass
class EarnPathReport:
    stages: list[Stage] = field(default_factory=list)
    completed_count: int = 0
    total_count: int = 0
    pct_complete: float = 0.0
    next_stage: str | None = None
    next_command: str | None = None
    next_title: str | None = None
    headline: str = ""


def _load_dotenv() -> dict[str, str]:
    """Read ./.env best-effort. Returns {} on missing /
    unreadable. Shared by all probes so env-var detection
    is consistent across stages."""
    out: dict[str, str] = {}
    try:
        from pathlib import Path
        p = Path(".env")
        if p.exists():
            for raw in p.read_text(
                encoding="utf-8",
            ).splitlines():
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    except OSError:
        pass
    return out


def _env_or_file(key: str) -> str | None:
    """Return os.environ[key] or the .env value; None when
    unset in both."""
    v = os.environ.get(key)
    if v:
        return v
    return _load_dotenv().get(key) or None


def _config_env_done() -> bool:
    """Stage 1: at least 5 of the 7 safe defaults set."""
    keys = (
        "SHOPAI_SPEND_CAP_DAILY_USD",
        "SHOPAI_AUTO_PAUSE_ON_OVERSPEND",
        "SHOPAI_AUTO_QUARANTINE_FROM_REVENUE",
        "SHOPAI_AUTO_DISARM_ON_OVERRIDE",
        "SHOPAI_CYCLE_RECORD_BRIEF",
        "SHOPAI_AI_STRATEGY",
        "SHOPAI_NOTIFY_AUTONOMY_COALESCE",
    )
    file_env = _load_dotenv()
    n_set = sum(
        1 for k in keys
        if os.environ.get(k) or file_env.get(k)
    )
    return n_set >= 5


def _notify_webhook_done() -> bool:
    # W963-90 fix: check .env too (operator may have run
    # earn-config --apply but not sourced .env yet).
    return bool(_env_or_file("SHOPAI_NOTIFY_WEBHOOK_URL"))


def _niches_done() -> bool:
    try:
        from data_pipeline.store.store_manager import (
            StoreManager,
        )
        stores = StoreManager().list_stores() or []
        if not stores:
            return False
        for s in stores:
            niche = str(s.get("niche") or "").strip().lower()
            if not niche or niche == "general":
                return False
        return True
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "earn_path: niches probe raised: %s", exc,
        )
        return False


def _catalog_seeded() -> bool:
    """Stage 4: at least 3 products on at least one store."""
    try:
        from data_pipeline.store.store_manager import (
            StoreManager,
        )
        sm = StoreManager()
        for s in sm.list_stores() or []:
            stats = sm.get_stats(s.get("store_id", "")) or {}
            n = int(stats.get("products", 0) or 0)
            if n >= 3:
                return True
        return False
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "earn_path: catalog probe raised: %s", exc,
        )
        return False


def _cron_scheduled() -> bool:
    """Stage 5: at least one cycle ran in last 24h."""
    try:
        from engines._cycle_history import last_run
        r = last_run()
        if r is None:
            return False
        age_h = (
            time.time() - float(r.started_at)
        ) / 3600.0
        return age_h <= 26.0  # < 26h means cron is alive
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "earn_path: cron probe raised: %s", exc,
        )
        return False


def _first_cycle_ran() -> bool:
    """Stage 6: any cycle ever ran."""
    try:
        from engines._cycle_history import last_run
        return last_run() is not None
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "earn_path: first_cycle probe raised: %s", exc,
        )
        return False


def _phase5_enabled() -> bool:
    # W963-90 fix: check .env too.
    return _env_or_file(
        "SHOPAI_AUTO_DISARM_ON_OVERRIDE",
    ) == "1"


def _is_earning() -> bool:
    """Stage 8: agi_earnings_summary verdict == earning."""
    try:
        from engines.agi_earnings_summary.summarizer \
            import compute_summary
        s = compute_summary(days=7)
        return s.verdict == "earning"
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "earn_path: earning probe raised: %s", exc,
        )
        return False


def _build_stages() -> list[Stage]:
    return [
        Stage(
            name="config_env",
            title="Configure env-vars",
            cli_command="shopai earn-config --apply",
            rationale=(
                "Apply 7 safe defaults to .env "
                "(spend cap, auto-pause, auto-quarantine, "
                "auto-disarm, snapshot recording, AI "
                "strategy, alert coalesce)."
            ),
        ),
        Stage(
            name="notify_webhook",
            title="Set Slack/Discord webhook",
            cli_command=(
                "export SHOPAI_NOTIFY_WEBHOOK_URL="
                "'https://hooks.slack.com/services/...'"
            ),
            rationale=(
                "Operator-specific URL. Receives "
                "critical alerts (anomaly / regression "
                "/ auto-disarm) inline in Slack."
            ),
        ),
        Stage(
            name="set_niches",
            title="Tag stores with niche",
            cli_command=(
                "shopai niche --set <store_id> "
                "<beauty|fashion|home|tech|food>"
            ),
            rationale=(
                "Niche-aware orchestrator biases cluster "
                "priorities per store."
            ),
        ),
        Stage(
            name="seed_catalog",
            title="Seed product catalog",
            cli_command=(
                "shopai earn-bootstrap --niche <X>"
            ),
            rationale=(
                "Cold-start chain: product candidates + "
                "content drafts + first launch."
            ),
        ),
        Stage(
            name="schedule_cron",
            title="Install cron schedule",
            cli_command=(
                "shopai cycle schedule --recommend"
            ),
            rationale=(
                "Recommender picks interval based on "
                "observed signal velocity. Install line "
                "in crontab / Task Scheduler."
            ),
        ),
        Stage(
            name="first_cycle",
            title="Kick off first cycle",
            cli_command="shopai cycle run --yes",
            rationale=(
                "First substantive cycle. Records Phase 4 "
                "snapshots; engines fire."
            ),
        ),
        Stage(
            name="enable_phase5",
            title="Enable auto-disarm safety net",
            cli_command=(
                "export SHOPAI_AUTO_DISARM_ON_OVERRIDE=1"
            ),
            rationale=(
                "W963-82: empire auto-pauses spend domains "
                "on critical override (loss streak / "
                "anomaly). Default OFF for safety; opt-in."
            ),
        ),
        Stage(
            name="earning",
            title="Monitor + scale",
            cli_command="shopai morning-brief",
            rationale=(
                "Empire is earning. Daily ritual + "
                "shopai cycle status to monitor."
            ),
        ),
    ]


def build_path() -> EarnPathReport:
    """Compute the on-ramp guide from current state."""
    stages = _build_stages()
    probes = {
        "config_env": _config_env_done,
        "notify_webhook": _notify_webhook_done,
        "set_niches": _niches_done,
        "seed_catalog": _catalog_seeded,
        "schedule_cron": _cron_scheduled,
        "first_cycle": _first_cycle_ran,
        "enable_phase5": _phase5_enabled,
        "earning": _is_earning,
    }
    # Walk stages; mark "done" while completed, then "next"
    # for the first incomplete, then "pending" for the rest.
    next_set = False
    for st in stages:
        done = probes.get(st.name, lambda: False)()
        if done:
            st.status = "done"
        elif not next_set:
            st.status = "next"
            next_set = True
        else:
            st.status = "pending"
    report = EarnPathReport(stages=stages)
    report.total_count = len(stages)
    report.completed_count = sum(
        1 for s in stages if s.status == "done"
    )
    report.pct_complete = (
        report.completed_count / report.total_count * 100.0
        if report.total_count else 0.0
    )
    next_stage = next(
        (s for s in stages if s.status == "next"),
        None,
    )
    if next_stage:
        report.next_stage = next_stage.name
        report.next_command = next_stage.cli_command
        report.next_title = next_stage.title
        # W963-95: use next_stage's actual 1-indexed
        # position. Pre-fix used completed_count+1, which
        # diverges from next_stage's position when stages
        # are completed out of order (operator can finish
        # stage 4 before stage 2; completed_count=2 but
        # next_stage is still stage 2 -> headline read
        # "Stage 3/8: <stage 2 title>" mismatch).
        next_idx = next(
            (i for i, s in enumerate(stages, start=1)
             if s is next_stage),
            report.completed_count + 1,
        )
        report.headline = (
            f"Stage {next_idx}/"
            f"{report.total_count}: {next_stage.title}"
        )
    else:
        # All done
        report.headline = (
            f"All {report.total_count} stage(s) complete "
            "-- empire is earning."
        )
    return report
