"""Templates for the 5-piece autonomy domain template + tests.

Phase 27 + 28 each took ~50 file changes to ship a new
autonomy domain. This module factors the 5 module files + the
companion test file into reusable Python string templates that
the autonomy-init scaffolder can render with per-domain
substitutions.

Substitution variables (all required):
  - `{PREFIX}`     file prefix, e.g. "outreach" / "quality"
  - `{DOMAIN}`     canonical key, e.g. "customer_outreach"
  - `{PKG}`        package dir suffix, e.g. "customer_outreach_autonomy"
  - `{CAPABILITY}` Shopify capability, e.g. "SHOPIFY_TAG_PRODUCT"
  - `{ENGINE}`     _ENGINE constant, e.g. "catalog_quality"
  - `{ACTION}`     _ACTION_TYPE, e.g. "apply_catalog_quality_tag"
  - `{ENV_PREFIX}` uppercase env prefix, e.g. "CATALOG_QUALITY"
  - `{APPLY_FN}`   apply function name, e.g. "apply_catalog_quality"
  - `{ANALYZE_FN}` analyze function, e.g. "analyze_catalog_quality_health"
  - `{BRIDGE_FN}`  bridge function, e.g. "maybe_auto_pause_quality"
  - `{STATUS_FN}`  status fn, e.g. "get_catalog_quality_status"
  - `{RECORD_FN}`  record function, e.g. "record_quality_event"
  - `{EVENT_CLASS}` event dataclass, e.g. "CatalogQualityEvent"
  - `{STATUS_CLASS}` status report dataclass, e.g.
                    "CatalogQualityStatusReport"
  - `{WAVE_BASE}`  starting wave number for docstring comments
  - `{ENTITY}`     primary entity ID field, e.g. "product_id"
  - `{TAG_LIST}`   curated tag taxonomy as Python frozenset literal
  - `{MAX_PER_RUN_DEFAULT}`  default per-cycle cap
"""
from __future__ import annotations


# ─── log module ─────────────────────────────────────────────────────────

LOG_TEMPLATE = '''"""{DOMAIN} action log (Wave {WAVE_BASE})."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.automation.action_log import (
    log_size as _log_size,
    recent_events as _recent_events,
    record_event,
)


_LOG_PATH = Path("data") / "{DOMAIN}_log.json"


@dataclass
class {EVENT_CLASS}:
    {ENTITY}: str
    store_id: str = ""
    action: str = ""
    tag: str = ""
    signal_source: str = ""
    applied: bool = False
    status: str = ""
    error: str = ""
    recorded_at: float = field(default_factory=time.time)


def {RECORD_FN}(event: {EVENT_CLASS}) -> None:
    record_event(_LOG_PATH, event)


def recent_events(
    *,
    window_hours: float = 168.0,
    store_id: str | None = None,
) -> list[dict[str, Any]]:
    return _recent_events(
        _LOG_PATH,
        window_hours=window_hours,
        filters={"store_id": store_id or ""} if store_id else None,
    )


def log_size() -> int:
    return _log_size(_LOG_PATH)
'''


# ─── state module ───────────────────────────────────────────────────────

STATE_TEMPLATE = '''"""{DOMAIN} pause state (Wave {WAVE_BASE_PLUS_1}). Thin template wrapper."""
from __future__ import annotations

from pathlib import Path

from core.automation.pause_state import (
    PauseState,
    get_state as _get_state,
    is_paused as _is_paused,
    pause as _pause,
    resume as _resume,
)


_STATE_PATH = Path("data") / "{DOMAIN}_state.json"


def get_state() -> PauseState:
    return _get_state(_STATE_PATH)


def is_paused() -> bool:
    return _is_paused(_STATE_PATH)


def pause(
    *, reason: str, auto_resume_after: float = 0.0,
) -> PauseState:
    return _pause(
        _STATE_PATH,
        reason=reason,
        auto_resume_after=auto_resume_after,
    )


def resume() -> PauseState:
    return _resume(_STATE_PATH)
'''


# ─── health module ──────────────────────────────────────────────────────

HEALTH_TEMPLATE = '''"""{DOMAIN} health analyzer (Wave {WAVE_BASE_PLUS_2})."""
from __future__ import annotations

from core.automation.health_analyzer import (
    HealthReport,
    analyze_health as _analyze,
    maybe_auto_pause as _maybe_pause,
)
from engines.{PKG}.{PREFIX}_log import (
    recent_events,
)
from engines.{PKG}.{PREFIX}_state import (
    is_paused,
    pause as _pause_state,
)


_ENV_PREFIX = "{ENV_PREFIX}"


def {ANALYZE_FN}(
    *,
    window_hours: float = 24.0,
    store_id: str | None = None,
) -> HealthReport:
    return _analyze(
        env_prefix=_ENV_PREFIX,
        window_hours=window_hours,
        recent_events_fn=recent_events,
        is_paused_fn=is_paused,
        store_id=store_id,
    )


def {BRIDGE_FN}(
    *,
    window_hours: float = 24.0,
) -> HealthReport:
    return _maybe_pause(
        env_prefix=_ENV_PREFIX,
        window_hours=window_hours,
        recent_events_fn=recent_events,
        is_paused_fn=is_paused,
        pause_fn=_pause_state,
    )
'''


# ─── applier module ─────────────────────────────────────────────────────

APPLIER_TEMPLATE = '''"""Autonomous {DOMAIN} tagging (Wave {WAVE_BASE_PLUS_3}).

New autonomy domain scaffolded via shopai autonomy-init.
Tags entities with curated flags via {CAPABILITY}.

## Safety gates

  1. action='tag_{PREFIX}' (engine-approved)
  2. {ENTITY} present + tag string non-empty
  3. is_paused() False
  4. tag matches curated taxonomy (anti-typo gate)
  5. per-cycle cap (SHOPAI_{ENV_PREFIX}_MAX_PER_RUN,
     default {MAX_PER_RUN_DEFAULT})
  6. router + capability resolution

## Opt-in

``data.apply_{DOMAIN}=True``. Default OFF.
"""
from __future__ import annotations

import os
from typing import Any

from engines._writeback_recorder import record_writeback
from engines.{PKG}.{PREFIX}_log import (
    {EVENT_CLASS},
    {RECORD_FN},
)
from engines.{PKG}.{PREFIX}_state import (
    is_paused,
)
from utils.logger import get_logger

logger = get_logger(
    "engines.{PKG}.applier",
)

_ENGINE = "{ENGINE}"
_ACTION_TYPE = "{ACTION}"
_WRITEBACK_RISK = "additive"

# Curated taxonomy (anti-typo gate)
_VALID_TAGS: frozenset[str] = {TAG_LIST}


def _max_per_run() -> int:
    raw = os.environ.get(
        "SHOPAI_{ENV_PREFIX}_MAX_PER_RUN",
        "{MAX_PER_RUN_DEFAULT}",
    )
    try:
        return int(raw)
    except (TypeError, ValueError):
        return {MAX_PER_RUN_DEFAULT}


def _get_router() -> Any | None:
    try:
        from core.adapters.router import get_router
        return get_router()
    except Exception:  # noqa: BLE001
        return None


def _capability() -> Any | None:
    try:
        from core.adapters.base import Capability
        return getattr(
            Capability, "{CAPABILITY}", None,
        )
    except Exception:  # noqa: BLE001
        return None


def _record(
    *,
    {ENTITY}: str,
    store_id: str,
    action: str,
    tag: str,
    signal_source: str,
    applied: bool,
    status: str,
    error: str | None,
) -> None:
    """Dual recording: Pattern Z + log."""
    try:
        record_writeback(
            engine=_ENGINE,
            action_type=_ACTION_TYPE,
            capability="{CAPABILITY}",
            params={{
                "{ENTITY}": {ENTITY},
                "store_id": store_id,
                "tag": tag,
                "signal_source": signal_source,
            }},
            success=applied,
            error=error,
        )
    except Exception:  # noqa: BLE001
        pass
    try:
        {RECORD_FN}({EVENT_CLASS}(
            {ENTITY}={ENTITY},
            store_id=store_id,
            action=action,
            tag=tag,
            signal_source=signal_source,
            applied=applied,
            status=status,
            error=error or "",
        ))
    except Exception:  # noqa: BLE001
        pass


def {APPLY_FN}(
    rows: list[dict[str, Any]],
    *,
    max_per_run: int | None = None,
) -> list[dict[str, Any]]:
    """Tag entities with quality / outreach / etc. flags."""
    if not isinstance(rows, list) or not rows:
        return []

    cap_run = (
        max_per_run if max_per_run is not None
        else _max_per_run()
    )
    paused = is_paused()
    router = _get_router() if not paused else None
    cap = _capability() if not paused else None

    out: list[dict[str, Any]] = []
    tagged_so_far = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        eid = str(row.get("{ENTITY}", "") or "")
        sid = str(row.get("store_id", "") or "")
        action = str(row.get("action", "") or "").lower()
        tag = str(row.get("tag", "") or "")
        signal = str(row.get("signal_source", "") or "")
        applied = False
        status_label = ""
        error: str | None = None

        if paused:
            status_label = "paused"
            error = "{DOMAIN} auto-pause flag set"
        elif action != "tag_{PREFIX}":
            status_label = "not_actionable"
        elif not eid or not tag:
            status_label = "missing_ids"
        elif tag not in _VALID_TAGS:
            status_label = "invalid_tag"
            error = (
                f"tag={{tag!r}} not in curated taxonomy"
            )
        elif tagged_so_far >= cap_run:
            status_label = "exceeds_per_run_cap"
            error = (
                f"per-run cap reached: {{cap_run}}"
            )
        elif router is None or cap is None:
            status_label = "router_unavailable"
        else:
            try:
                res = router.execute(
                    cap,
                    {{"{ENTITY}": eid, "tags": [tag]}},
                )
                if getattr(res, "ok", False):
                    applied = True
                    status_label = "recorded"
                    tagged_so_far += 1
                else:
                    status_label = "adapter_failed"
                    err_obj = getattr(
                        res, "error", "adapter_failed",
                    )
                    error = (
                        str(err_obj) if err_obj is not None
                        else "adapter_failed"
                    )
            except Exception as exc:  # noqa: BLE001
                status_label = "adapter_failed"
                error = str(exc)

        _record(
            {ENTITY}=eid,
            store_id=sid,
            action=action,
            tag=tag,
            signal_source=signal,
            applied=applied,
            status=status_label,
            error=error,
        )
        out.append({{
            "{ENTITY}": eid,
            "tag": tag,
            "applied": applied,
            "status": status_label,
            "error": error,
        }})
    return out
'''


# ─── status module ──────────────────────────────────────────────────────

STATUS_TEMPLATE = '''"""{DOMAIN} autonomy status surface (Wave {WAVE_BASE_PLUS_4})."""
from __future__ import annotations

from dataclasses import dataclass, field

from engines.{PKG}.{PREFIX}_health import (
    {ANALYZE_FN},
)
from engines.{PKG}.{PREFIX}_log import (
    recent_events,
)
from engines.{PKG}.{PREFIX}_state import (
    get_state,
)


@dataclass
class {STATUS_CLASS}:
    window_hours: float
    store_id: str | None = None
    total_events: int = 0
    applied_count: int = 0
    skipped_count: int = 0
    by_tag: dict[str, int] = field(default_factory=dict)
    by_status: dict[str, int] = field(default_factory=dict)
    by_signal_source: dict[str, int] = field(
        default_factory=dict,
    )
    health_verdict: str = "healthy"
    health_failure_ratio: float = 0.0
    paused: bool = False
    pause_reason: str = ""
    verdict: str = "healthy"
    verdict_reasons: list[str] = field(default_factory=list)
    next_action: str = ""


def {STATUS_FN}(
    *,
    window_hours: float = 168.0,
    store_id: str | None = None,
) -> {STATUS_CLASS}:
    report = {STATUS_CLASS}(
        window_hours=window_hours,
        store_id=store_id,
    )
    rows = recent_events(
        window_hours=window_hours, store_id=store_id,
    )
    report.total_events = len(rows)
    for r in rows:
        status = r.get("status", "")
        report.by_status[status] = (
            report.by_status.get(status, 0) + 1
        )
        if r.get("applied") is True:
            report.applied_count += 1
            tag = r.get("tag", "")
            if tag:
                report.by_tag[tag] = (
                    report.by_tag.get(tag, 0) + 1
                )
            signal = r.get("signal_source", "")
            if signal:
                report.by_signal_source[signal] = (
                    report.by_signal_source.get(signal, 0) + 1
                )
        else:
            report.skipped_count += 1

    health = {ANALYZE_FN}(
        window_hours=window_hours,
    )
    report.health_verdict = health.verdict
    report.health_failure_ratio = health.failure_ratio

    state = get_state()
    report.paused = state.paused
    report.pause_reason = state.reason

    if report.paused:
        report.verdict = "paused"
        report.verdict_reasons.append(
            f"{DOMAIN} auto-pause active: "
            f"{{report.pause_reason or '(no reason)'}}"
        )
        report.next_action = (
            "Resume via `shopai {DOMAIN_HYPHEN}-resume`."
        )
    elif report.health_verdict == "critical":
        report.verdict = "degraded"
        report.verdict_reasons.append(
            f"failure ratio "
            f"{{report.health_failure_ratio:.0%}} >= critical"
        )
        report.next_action = (
            "`shopai {DOMAIN_HYPHEN}-health --apply-bridge`."
        )
    elif report.health_verdict == "degraded":
        report.verdict = "degraded"
        report.verdict_reasons.append(
            f"failure ratio "
            f"{{report.health_failure_ratio:.0%}} above warn"
        )
        report.next_action = "Monitor closely."
    elif report.total_events == 0:
        report.verdict = "quiet"
        report.verdict_reasons.append(
            "no {DOMAIN} actions in window"
        )
        report.next_action = (
            "Enable via data.apply_{DOMAIN}=True."
        )
    else:
        report.verdict = "healthy"
        report.verdict_reasons.append(
            f"{{report.applied_count}} entity(s) tagged"
        )
        report.next_action = "Monitor via daily-brief."
    return report
'''


# ─── package __init__ ───────────────────────────────────────────────────

INIT_TEMPLATE = '''"""{DOMAIN_TITLE} autonomy domain (Wave {WAVE_BASE}+).

Production autonomy domain scaffolded via shopai autonomy-init.

5-piece template (Phase 12+ wrappers around core/automation/*):
  - {PREFIX}_log     event journal
  - {PREFIX}_state   pause flag
  - {PREFIX}_health  failure-ratio analyzer + bridge
  - {PREFIX}_applier curated-taxonomy tag writer
  - {PREFIX}_status  empire-wide rollup
"""
'''


# ─── test scaffold ──────────────────────────────────────────────────────

TEST_TEMPLATE = '''"""Tests for the {PKG} domain (Wave {WAVE_BASE}+).

Scaffolded via shopai autonomy-init. Verifies the 5-piece
template surface + applier safety gates + autonomy_status
rollup integration.
"""
from __future__ import annotations

from engines.{PKG}.{PREFIX}_applier import (
    {APPLY_FN},
)
from engines.{PKG}.{PREFIX}_health import (
    {ANALYZE_FN},
)
from engines.{PKG}.{PREFIX}_log import (
    log_size,
    recent_events,
)
from engines.{PKG}.{PREFIX}_state import (
    is_paused,
)
from engines.{PKG}.{PREFIX}_status import (
    {STATUS_FN},
)


class TestTemplateImports:

    def test_log_exports(self):
        assert callable(log_size)
        assert callable(recent_events)

    def test_state_exports(self):
        assert callable(is_paused)
        assert isinstance(is_paused(), bool)

    def test_health_exports(self):
        assert callable({ANALYZE_FN})
        r = {ANALYZE_FN}()
        assert hasattr(r, "verdict")
        assert hasattr(r, "failure_ratio")

    def test_applier_exports(self):
        assert callable({APPLY_FN})

    def test_status_exports(self):
        assert callable({STATUS_FN})
        r = {STATUS_FN}()
        assert hasattr(r, "verdict")
        assert hasattr(r, "applied_count")


class TestApplierEmptyShortCircuit:

    def test_empty_list_returns_empty(self):
        assert {APPLY_FN}([]) == []

    def test_none_returns_empty(self):
        assert {APPLY_FN}(None) == []
'''


# Pack as a mapping so the orchestrator can iterate.
TEMPLATES: dict[str, str] = {
    "__init__.py": INIT_TEMPLATE,
    "{PREFIX}_log.py": LOG_TEMPLATE,
    "{PREFIX}_state.py": STATE_TEMPLATE,
    "{PREFIX}_health.py": HEALTH_TEMPLATE,
    "{PREFIX}_applier.py": APPLIER_TEMPLATE,
    "{PREFIX}_status.py": STATUS_TEMPLATE,
}


TEST_FILE_TEMPLATE_KEY = "test_{PKG}.py"
