"""Detect missing config + apply safe defaults."""
from __future__ import annotations

import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# W963-92: canonical Pattern J guard + atomic text writer
# (the .env file is text-not-JSON; atomic_write_text gives
# the same crash-safe guarantees as atomic_write_json).
from core.agi.persistence import (
    atomic_write_text as _atomic_write_text,
    is_test_environment as _is_test_environment,
)

logger = logging.getLogger(__name__)


_ENV_FILE = Path(".env")

# Safe defaults: env-var -> (value, rationale, operator_specific)
# When operator_specific=True, the wizard NEVER writes a value
# automatically (the operator must supply it).
@dataclass
class ConfigKey:
    name: str
    default: str
    rationale: str
    operator_specific: bool = False
    fix_command: str = ""


_SAFE_DEFAULTS: list[ConfigKey] = [
    ConfigKey(
        name="SHOPAI_SPEND_CAP_DAILY_USD",
        default="50",
        rationale=(
            "Per-day spend ceiling. $50 is a safe starter "
            "for a new empire."
        ),
        fix_command=(
            "export SHOPAI_SPEND_CAP_DAILY_USD=50"
        ),
    ),
    ConfigKey(
        name="SHOPAI_AUTO_PAUSE_ON_OVERSPEND",
        default="1",
        rationale=(
            "Pauses spend engines when daily cap is "
            "breached."
        ),
        fix_command="export SHOPAI_AUTO_PAUSE_ON_OVERSPEND=1",
    ),
    ConfigKey(
        name="SHOPAI_AUTO_QUARANTINE_FROM_REVENUE",
        default="1",
        rationale=(
            "Auto-quarantine engines whose attribution "
            "drops below thresholds."
        ),
        fix_command=(
            "export SHOPAI_AUTO_QUARANTINE_FROM_REVENUE=1"
        ),
    ),
    ConfigKey(
        name="SHOPAI_AUTO_DISARM_ON_OVERRIDE",
        default="1",
        rationale=(
            "W963-82 Phase 5 auto-response: empire "
            "auto-disarms spend domains on critical "
            "override."
        ),
        fix_command=(
            "export SHOPAI_AUTO_DISARM_ON_OVERRIDE=1"
        ),
    ),
    ConfigKey(
        name="SHOPAI_CYCLE_RECORD_BRIEF",
        default="1",
        rationale=(
            "W963-62 self-bootstrap: cycle records "
            "Phase 4 history snapshots without separate "
            "cron."
        ),
        fix_command=(
            "export SHOPAI_CYCLE_RECORD_BRIEF=1"
        ),
    ),
    ConfigKey(
        name="SHOPAI_AI_STRATEGY",
        default="1",
        rationale=(
            "Enables LLM consultant overlay on the AI "
            "strategy layer. Requires OPENAI_API_KEY."
        ),
        fix_command="export SHOPAI_AI_STRATEGY=1",
    ),
    ConfigKey(
        name="SHOPAI_NOTIFY_AUTONOMY_COALESCE",
        default="1",
        rationale=(
            "Coalesces per-domain autonomy alerts into a "
            "single rollup notification."
        ),
        fix_command=(
            "export SHOPAI_NOTIFY_AUTONOMY_COALESCE=1"
        ),
    ),
    # Operator-specific (NOT auto-applied)
    ConfigKey(
        name="SHOPAI_NOTIFY_WEBHOOK_URL",
        default="https://hooks.slack.com/services/...",
        rationale=(
            "Slack/Discord webhook URL. Operator-specific "
            "-- supply your own."
        ),
        operator_specific=True,
        fix_command=(
            "export SHOPAI_NOTIFY_WEBHOOK_URL="
            "'https://hooks.slack.com/services/...'"
        ),
    ),
    ConfigKey(
        name="OPENAI_API_KEY",
        default="sk-...",
        rationale=(
            "OpenAI API key for the LLM consultant "
            "(W963-65/66). Operator-specific."
        ),
        operator_specific=True,
        fix_command="export OPENAI_API_KEY='sk-...'",
    ),
]


@dataclass
class KeyState:
    name: str
    is_set_env: bool
    is_set_file: bool
    current_value: str | None
    default: str
    rationale: str
    operator_specific: bool
    fix_command: str


@dataclass
class ConfigReport:
    keys: list[KeyState] = field(default_factory=list)
    n_total: int = 0
    n_already_set: int = 0
    n_applicable: int = 0  # safe-defaults that can apply
    n_operator_specific_missing: int = 0
    applied_count: int = 0
    dry_run: bool = True
    env_file_path: str = ""
    headline: str = ""
    next_action: str = ""


def _load_env_file() -> dict[str, str]:
    """Parse ./.env into a dict. Returns {} if file missing
    or unreadable. Tolerant of comments / blank lines.
    Values are taken verbatim (no quote stripping) so
    operator-supplied quoted values round-trip."""
    if not _ENV_FILE.exists():
        return {}
    out: dict[str, str] = {}
    try:
        for raw in _ENV_FILE.read_text(
            encoding="utf-8",
        ).splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    except OSError as exc:
        logger.debug("earn_config: env load: %s", exc)
    return out


def _atomic_write_env(entries: dict[str, str]) -> bool:
    """Write the env entries to ./.env atomically.
    Preserves keys NOT in entries via merge with current
    file contents.

    W963-92: delegates the actual write to the canonical
    atomic_write_text() so any future atomic-write fix
    (e.g. fsync-before-replace) lives in one place.
    """
    current = _load_env_file()
    current.update(entries)
    lines = [
        f"{k}={v}" for k, v in sorted(current.items())
    ]
    body = "\n".join(lines) + "\n"
    return _atomic_write_text(_ENV_FILE, body)


# W963-92: _is_test_environment imported from core.agi.persistence above.


def build_state() -> ConfigReport:
    """Inspect current env + .env file; build per-key state."""
    file_env = _load_env_file()
    report = ConfigReport(
        env_file_path=str(_ENV_FILE),
        dry_run=True,
    )
    for key in _SAFE_DEFAULTS:
        env_val = os.environ.get(key.name)
        file_val = file_env.get(key.name)
        is_set_env = bool(env_val and env_val.strip())
        is_set_file = bool(file_val and file_val.strip())
        # Treat known-placeholder values as unset. Explicit
        # exact-match against the documented defaults rather
        # than the operator-precedence-prone chain that
        # caused W963-72 (and / or wrong binding flagged any
        # value ending in '...' as a placeholder).
        cur = env_val or file_val
        if cur in {
            "sk-...",
            "https://hooks.slack.com/services/...",
        }:
            cur = None
            is_set_env = False
            is_set_file = False
        state = KeyState(
            name=key.name,
            is_set_env=is_set_env,
            is_set_file=is_set_file,
            current_value=cur,
            default=key.default,
            rationale=key.rationale,
            operator_specific=key.operator_specific,
            fix_command=key.fix_command,
        )
        report.keys.append(state)
        if is_set_env or is_set_file:
            report.n_already_set += 1
        elif not key.operator_specific:
            report.n_applicable += 1
        else:
            report.n_operator_specific_missing += 1
    report.n_total = len(report.keys)
    report.headline = (
        f"{report.n_already_set}/{report.n_total} set; "
        f"{report.n_applicable} safe defaults can apply; "
        f"{report.n_operator_specific_missing} need "
        "operator input"
    )
    return report


def apply_defaults() -> ConfigReport:
    """Write safe defaults for unset keys. Skips operator-
    specific keys."""
    report = build_state()
    if _is_test_environment():
        report.next_action = (
            "Pattern J test guard active; would have "
            "written .env"
        )
        return report
    to_write: dict[str, str] = {}
    for st in report.keys:
        if st.is_set_env or st.is_set_file:
            continue
        if st.operator_specific:
            continue
        to_write[st.name] = st.default
    if not to_write:
        report.next_action = (
            "All safe defaults already set."
        )
        return report
    ok = _atomic_write_env(to_write)
    if ok:
        report.applied_count = len(to_write)
        report.dry_run = False
        report.next_action = (
            f"Wrote {len(to_write)} default(s) to .env. "
            "Source it: source .env"
        )
    else:
        report.next_action = (
            "Write failed -- check filesystem permissions."
        )
    return report


def print_exports() -> list[str]:
    """Return shell export commands for missing safe
    defaults so operator can copy/paste."""
    report = build_state()
    return [
        f"export {st.name}={st.default}"
        for st in report.keys
        if not (st.is_set_env or st.is_set_file)
        and not st.operator_specific
    ]
