"""Health check — answer "can ShopAI actually work right now?"

Owner-facing diagnostic that runs through every subsystem and
reports actionable fix-it-yourself instructions. Before this
module existed, a fresh clone would silently half-work: Shopify
bridge unavailable (fetch phase errors each cycle), Meta Ads
adapter unconfigured (campaign creation fails), webhooks
unregistered (OutcomeRecorder never fires on real orders),
compute budgets missing (LLM cost caps absent), brain hooks off
(v33-v38 learners stay idle) — and nothing told the owner which
of those were the problem.

Each check returns a ``CheckResult`` with:

  * name
  * status — ``ok`` / ``warn`` / ``fail`` / ``skipped``
  * summary — one-sentence human-readable state
  * fix      — actionable next step (empty if status=ok)
  * details — optional dict for the ``shopai doctor --json`` mode

``run_all`` returns a ``HealthReport`` aggregating every check plus
an overall verdict (``ready`` / ``degraded`` / ``blocked``) and a
ranked list of fixes.

Pure stdlib. No network calls by default — file/env checks only.
Network-dependent checks (Shopify credentials validate, Meta
credentials validate, webhook registered) are opt-in via
``run_all(network=True)`` so a dry ``shopai doctor`` stays fast.
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from utils.logger import get_logger


logger = get_logger("readiness.health_check")


# ── Result dataclasses ──────────────────────────────────────


@dataclass
class CheckResult:
    name: str
    status: str            # "ok" | "warn" | "fail" | "skipped"
    summary: str
    fix: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    ts: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "summary": self.summary,
            "fix": self.fix,
            "details": dict(self.details),
            "ts": self.ts,
        }


@dataclass
class HealthReport:
    verdict: str           # "ready" | "degraded" | "blocked"
    checks: list[CheckResult]
    fixes: list[str]
    generated_ts: float

    @property
    def ok_count(self) -> int:
        return sum(1 for c in self.checks if c.status == "ok")

    @property
    def warn_count(self) -> int:
        return sum(1 for c in self.checks if c.status == "warn")

    @property
    def fail_count(self) -> int:
        return sum(1 for c in self.checks if c.status == "fail")

    def as_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "checks": [c.as_dict() for c in self.checks],
            "fixes": list(self.fixes),
            "ok_count": self.ok_count,
            "warn_count": self.warn_count,
            "fail_count": self.fail_count,
            "generated_ts": self.generated_ts,
        }

    def as_text(self) -> str:
        """Owner-friendly plain-text rendering."""
        status_icon = {
            "ok": "✓", "warn": "!", "fail": "✗", "skipped": "-",
        }
        lines = [
            f"ShopAI health: {self.verdict}",
            (
                f"  {self.ok_count} ok · "
                f"{self.warn_count} warn · "
                f"{self.fail_count} fail"
            ),
            "",
        ]
        for c in self.checks:
            icon = status_icon.get(c.status, "?")
            lines.append(f"  [{icon}] {c.name}: {c.summary}")
            if c.fix:
                lines.append(f"      → {c.fix}")
        if self.fixes:
            lines.append("")
            lines.append("Top fixes:")
            for f in self.fixes:
                lines.append(f"  · {f}")
        return "\n".join(lines)


# ── Individual checks ───────────────────────────────────────


def _required_env(
    key: str, what: str,
) -> CheckResult:
    val = os.getenv(key, "")
    if val:
        return CheckResult(
            name=f"env:{key}",
            status="ok",
            summary=f"{what} configured",
            ts=time.time(),
        )
    return CheckResult(
        name=f"env:{key}",
        status="fail",
        summary=f"{what} missing",
        fix=(
            f"Set {key}=<your value> in .env or export it; "
            f"see .env.example."
        ),
        ts=time.time(),
    )


def check_shopify_credentials() -> CheckResult:
    url = os.getenv("SHOPAI_SHOPIFY_URL", "")
    key = os.getenv(
        "SHOPAI_SHOPIFY_KEY",
        os.getenv("SHOPAI_SHOPIFY_CLIENT_SECRET", ""),
    )
    missing = []
    if not url:
        missing.append("SHOPAI_SHOPIFY_URL")
    if not key:
        missing.append(
            "SHOPAI_SHOPIFY_KEY (or SHOPAI_SHOPIFY_CLIENT_SECRET)",
        )
    if missing:
        return CheckResult(
            name="shopify.credentials",
            status="fail",
            summary=(
                "Shopify credentials missing: "
                + ", ".join(missing)
            ),
            fix=(
                "Add Shopify admin API credentials to .env. Without "
                "them, data fetch + product creation + webhook "
                "registration all no-op."
            ),
            details={"missing": missing},
            ts=time.time(),
        )
    return CheckResult(
        name="shopify.credentials",
        status="ok",
        summary=f"Shopify credentials present for {url}",
        details={"shop_url": url},
        ts=time.time(),
    )


def check_meta_ads_credentials() -> CheckResult:
    token = os.getenv(
        "META_ACCESS_TOKEN",
        os.getenv("meta_ads_access_token", ""),
    )
    account_id = os.getenv(
        "META_ADS_ACCOUNT_ID",
        os.getenv("meta_ads_account_id", ""),
    )
    if not token and not account_id:
        return CheckResult(
            name="meta_ads.credentials",
            status="warn",
            summary=(
                "Meta Ads token + account id not set — "
                "ads disabled"
            ),
            fix=(
                "Add META_ACCESS_TOKEN and META_ADS_ACCOUNT_ID to "
                ".env. Needed for publisher_bundle to launch "
                "campaigns. Skip if you don't run Meta ads."
            ),
            ts=time.time(),
        )
    if not token or not account_id:
        return CheckResult(
            name="meta_ads.credentials",
            status="fail",
            summary="Meta Ads credentials partial",
            fix=(
                "Both META_ACCESS_TOKEN and META_ADS_ACCOUNT_ID "
                "are required. Partial config fails silently."
            ),
            details={
                "has_token": bool(token),
                "has_account_id": bool(account_id),
            },
            ts=time.time(),
        )
    return CheckResult(
        name="meta_ads.credentials",
        status="ok",
        summary=f"Meta Ads credentials present ({account_id})",
        details={"account_id": account_id},
        ts=time.time(),
    )


def check_live_execution_flags() -> CheckResult:
    env = os.getenv("SHOPAI_ENABLE_LIVE_EXECUTION", "")
    live_on = env == "1"
    # Also check config/settings.json when it exists
    cfg_path = Path("config/settings.json")
    cfg_live = None
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text())
            cfg_live = bool(cfg.get("enable_live_execution"))
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "settings.json parse failed: %s", exc,
            )
    if not live_on:
        return CheckResult(
            name="live_execution.flag",
            status="warn",
            summary=(
                "Live writes disabled — safe default, but nothing "
                "will be written to Shopify/Meta"
            ),
            fix=(
                "Set SHOPAI_ENABLE_LIVE_EXECUTION=1 AND "
                "LaunchRequest.live=True to actually write to "
                "external services. Per CLAUDE.md §4b/G this is a "
                "double gate — intentional."
            ),
            details={
                "env": env,
                "config_json": cfg_live,
            },
            ts=time.time(),
        )
    return CheckResult(
        name="live_execution.flag",
        status="ok",
        summary=(
            "Live execution enabled — real writes will land"
        ),
        ts=time.time(),
    )


def check_brain_hooks() -> CheckResult:
    on = os.getenv("SHOPAI_BRAIN_HOOKS", "") == "1"
    if not on:
        return CheckResult(
            name="brain.hooks",
            status="warn",
            summary=(
                "Brain hooks off — v33-v38 learners won't see "
                "signals"
            ),
            fix=(
                "Set SHOPAI_BRAIN_HOOKS=1 to enable outcome loop + "
                "failure classification + insight synthesis. See "
                "CLAUDE.md §4c for the loop this enables."
            ),
            ts=time.time(),
        )
    return CheckResult(
        name="brain.hooks",
        status="ok",
        summary=(
            "Brain hooks enabled — learners see real signals"
        ),
        ts=time.time(),
    )


def check_compute_budget() -> CheckResult:
    """The compute_budget only gets populated during a live cycle.
    This check warns when budgets haven't been registered — useful
    signal in a pre-cycle environment."""
    try:
        from core.brain.brain_facade import _compute_budget
        cb = _compute_budget()
        stats = cb.stats()
        if stats.get("budgets"):
            return CheckResult(
                name="compute_budget",
                status="ok",
                summary=(
                    f"{len(stats['budgets'])} budgets "
                    "registered"
                ),
                details=dict(stats),
                ts=time.time(),
            )
        return CheckResult(
            name="compute_budget",
            status="warn",
            summary=(
                "No compute budgets registered yet — first cycle "
                "will register defaults"
            ),
            fix=(
                "Run a cycle via main.py or core_orchestrator to "
                "register default caps (latency 30s, usd $0.10, "
                "api_calls 500)."
            ),
            ts=time.time(),
        )
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name="compute_budget",
            status="skipped",
            summary=f"Could not import compute_budget: {exc}",
            ts=time.time(),
        )


def check_obsidian_vault() -> CheckResult:
    path = os.getenv("OBSIDIAN_VAULT_PATH", "./vault")
    p = Path(path)
    if not p.exists():
        return CheckResult(
            name="obsidian.vault",
            status="warn",
            summary=f"Vault directory {path} does not exist",
            fix=(
                f"Create {path}/ or point OBSIDIAN_VAULT_PATH "
                "to an existing Obsidian vault; decisions + "
                "wins + errors will mirror there per CLAUDE.md §5."
            ),
            ts=time.time(),
        )
    if not p.is_dir():
        return CheckResult(
            name="obsidian.vault",
            status="fail",
            summary=f"{path} exists but is not a directory",
            fix=(
                f"Remove {path} or point OBSIDIAN_VAULT_PATH "
                "elsewhere."
            ),
            ts=time.time(),
        )
    expected = ("Decisions", "Wins", "Errors", "Knowledge")
    missing = [
        sub for sub in expected
        if not (p / sub).exists()
    ]
    if missing:
        return CheckResult(
            name="obsidian.vault",
            status="warn",
            summary=(
                f"Vault at {path} missing {len(missing)} "
                "subdirectories"
            ),
            fix=(
                f"Create {'/'.join(expected)} under {path}/ so "
                "the vault bridge can mirror into the expected "
                "layout."
            ),
            details={"missing": missing},
            ts=time.time(),
        )
    return CheckResult(
        name="obsidian.vault",
        status="ok",
        summary=f"Vault ready at {path}",
        ts=time.time(),
    )


def check_data_dir() -> CheckResult:
    p = Path("data")
    if not p.exists():
        return CheckResult(
            name="data.dir",
            status="warn",
            summary="data/ directory missing",
            fix=(
                "Create data/ — SQLite databases (journal, "
                "knowledge_base, brain learners) live there."
            ),
            ts=time.time(),
        )
    return CheckResult(
        name="data.dir",
        status="ok",
        summary="data/ directory present",
        ts=time.time(),
    )


def check_webhook_registered(
    *, http: Any = None,
) -> CheckResult:
    """Calls Shopify Admin API to verify orders/paid webhook is
    registered. Network — skipped in dry mode."""
    url = os.getenv("SHOPAI_SHOPIFY_URL", "")
    key = os.getenv(
        "SHOPAI_SHOPIFY_KEY",
        os.getenv("SHOPAI_SHOPIFY_CLIENT_SECRET", ""),
    )
    if not url or not key:
        return CheckResult(
            name="shopify.webhook",
            status="skipped",
            summary=(
                "Cannot check webhook without Shopify credentials"
            ),
            ts=time.time(),
        )
    try:
        from execution.launch.shopify_attribution import (
            list_registered_webhooks,
        )
        webhooks = list_registered_webhooks(
            url, key, http=http,
        )
        has_paid = any(
            w.get("topic") == "orders/paid" for w in webhooks
        )
        if has_paid:
            return CheckResult(
                name="shopify.webhook",
                status="ok",
                summary=(
                    f"{len(webhooks)} webhooks registered, "
                    "orders/paid present"
                ),
                details={"count": len(webhooks)},
                ts=time.time(),
            )
        return CheckResult(
            name="shopify.webhook",
            status="fail",
            summary="orders/paid webhook NOT registered",
            fix=(
                "Call execution.launch.shopify_attribution."
                "ensure_attribution(shop_url, api_key, "
                "callback_url=<your ShopAI ingress URL>). "
                "Without this webhook, OrderWebhookHandler never "
                "fires and the outcome learning loop is open."
            ),
            details={"count": len(webhooks)},
            ts=time.time(),
        )
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name="shopify.webhook",
            status="fail",
            summary=f"Webhook check failed: {exc}",
            fix=(
                "Verify Shopify URL + API key; see "
                "shopify.credentials above."
            ),
            ts=time.time(),
        )


# ── Runner ──────────────────────────────────────────────────


_DEFAULT_CHECKS: tuple[Callable[[], CheckResult], ...] = (
    check_shopify_credentials,
    check_meta_ads_credentials,
    check_live_execution_flags,
    check_brain_hooks,
    check_compute_budget,
    check_obsidian_vault,
    check_data_dir,
)


def _verdict(checks: list[CheckResult]) -> str:
    if any(c.status == "fail" for c in checks):
        return "blocked"
    if any(c.status == "warn" for c in checks):
        return "degraded"
    return "ready"


_lock = threading.Lock()


def run_all(
    *,
    network: bool = False,
    extra_checks: tuple[Callable[[], CheckResult], ...] = (),
    http: Any = None,
) -> HealthReport:
    """Run every configured check and aggregate.

    Pass ``network=True`` to also run the webhook-registered check
    which calls Shopify Admin API. Default is network-free.
    """
    with _lock:
        checks_to_run: list[Callable[[], CheckResult]] = list(
            _DEFAULT_CHECKS,
        )
        if network:
            # Webhook check relies on http client; wrap to pass it
            def _webhook():
                return check_webhook_registered(http=http)

            checks_to_run.append(_webhook)
        for extra in extra_checks:
            checks_to_run.append(extra)
    results: list[CheckResult] = []
    for fn in checks_to_run:
        try:
            res = fn()
            if not isinstance(res, CheckResult):
                res = CheckResult(
                    name=getattr(fn, "__name__", "check"),
                    status="fail",
                    summary="check returned non-CheckResult",
                    ts=time.time(),
                )
        except Exception as exc:  # noqa: BLE001
            res = CheckResult(
                name=getattr(fn, "__name__", "check"),
                status="fail",
                summary=f"check raised: {exc}",
                fix=(
                    "Inspect the stack; this should be reported "
                    "as a ShopAI bug."
                ),
                ts=time.time(),
            )
            logger.debug(
                "health check %s raised: %s", fn, exc,
            )
        results.append(res)
    fixes = [
        c.fix for c in results
        if c.status in ("fail", "warn") and c.fix
    ]
    return HealthReport(
        verdict=_verdict(results),
        checks=results,
        fixes=fixes,
        generated_ts=time.time(),
    )
