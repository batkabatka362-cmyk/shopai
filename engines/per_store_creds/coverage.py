"""Discovery: scan os.environ for SHOPAI_STORE_<SID>_*
per-store override variables, group by store + adapter.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class StoreCoverage:
    """Per-store override summary."""
    store_id: str
    overrides: list[str] = field(default_factory=list)
    # Mapping from env var name -> set/unset
    raw_vars: dict[str, bool] = field(
        default_factory=dict,
    )

    @property
    def override_count(self) -> int:
        return len(self.overrides)


# Reverse-map known alias names -> readable labels for
# operator output. Sources from
# core.adapters.config.ENV_ALIASES + common per-store
# customization knobs (account_id etc.).
_KNOWN_SUFFIXES = (
    # LLM
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GROQ_API_KEY",
    "GEMINI_API_KEY",
    "MISTRAL_API_KEY",
    "DEEPSEEK_API_KEY",
    "OPENROUTER_API_KEY",
    "HUGGINGFACE_API_KEY",
    # Email
    "KLAVIYO_API_KEY",
    "BREVO_API_KEY",
    "RESEND_API_KEY",
    # Ads
    "META_ADS_ACCESS_TOKEN",
    "META_ADS_ACCOUNT_ID",
    "GOOGLE_ADS_DEVELOPER_TOKEN",
    "GOOGLE_ADS_CLIENT_ID",
    "GOOGLE_ADS_CLIENT_SECRET",
    "GOOGLE_ADS_REFRESH_TOKEN",
    "GOOGLE_ADS_CUSTOMER_ID",
    # Voice / media
    "ELEVENLABS_API_KEY",
    "PEXELS_API_KEY",
    "PIXABAY_API_KEY",
    # Sourcing
    "CJ_API_KEY",
    "AUTODS_API_TOKEN",
    # Ad spy
    "MINEA_API_KEY",
    "PIPIADS_API_KEY",
    "BIGSPY_API_KEY",
    # Search
    "SERPER_API_KEY",
    "BRAVE_API_KEY",
    "TAVILY_API_KEY",
    "PERPLEXITY_API_KEY",
    # Shopify direct (caller can supply per-store
    # overrides for the Shopify creds too if needed)
    "SHOPAI_SHOPIFY_URL",
    "SHOPAI_SHOPIFY_KEY",
    # Daily budget caps (W963-119)
    "DAILY_BUDGET_USD",
)


def _denormalise_sid(sid_env: str) -> str:
    """Reverse W963-116's normaliser: STORE_A -> store_a
    is the COMMON case. Lossy: hyphen-original sids
    can't be recovered.

    We surface the env-var-style sid as-is + let the
    operator interpret. The CLI renderer can hyphenate
    by inspecting StoreManager registered store_ids
    if needed.
    """
    return sid_env.lower()


def _scan_envvar(
    name: str,
) -> tuple[str, str] | None:
    """Parse SHOPAI_STORE_<SID>_<SUFFIX>. Returns
    (sid_env_form, suffix) on match, None otherwise."""
    if not name.startswith("SHOPAI_STORE_"):
        return None
    body = name[len("SHOPAI_STORE_"):]
    # Find the longest matching known suffix
    for suffix in _KNOWN_SUFFIXES:
        token = "_" + suffix
        if body.endswith(token):
            sid_env = body[:-len(token)]
            if sid_env:
                return sid_env, suffix
    return None


def discover_coverage(
    *, only_store: str = "",
) -> list[StoreCoverage]:
    """Walk os.environ, find all SHOPAI_STORE_<SID>_*
    variables, return per-store grouped coverage.

    Stores registered in StoreManager but WITHOUT any
    per-store env override are still included (with
    empty overrides list) so operator sees them.

    only_store filter: when supplied, restrict the
    output to that single store_id (case-insensitive
    match against env-form or raw form).
    """
    # Pass 1: scan env vars
    by_sid: dict[str, StoreCoverage] = {}
    for env_name, val in os.environ.items():
        parsed = _scan_envvar(env_name)
        if not parsed:
            continue
        sid_env, suffix = parsed
        sid = _denormalise_sid(sid_env)
        cov = by_sid.setdefault(
            sid, StoreCoverage(store_id=sid),
        )
        if suffix not in cov.overrides:
            cov.overrides.append(suffix)
        cov.raw_vars[env_name] = bool(val)

    # Pass 2: include StoreManager stores with no
    # overrides (so operator sees them as "using fleet
    # defaults")
    try:
        from data_pipeline.store.store_manager import (
            StoreManager,
        )
        for row in StoreManager().list_stores() or []:
            if not isinstance(row, dict):
                continue
            sid = row.get("store_id")
            if (
                isinstance(sid, str) and sid
                and sid not in by_sid
            ):
                by_sid[sid] = StoreCoverage(
                    store_id=sid,
                )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "discover_coverage: StoreManager raised %s",
            exc,
        )

    out = list(by_sid.values())
    if only_store:
        needle = only_store.strip().lower()
        out = [
            c for c in out
            if c.store_id.lower() == needle
        ]
    out.sort(
        key=lambda c: (
            -c.override_count,
            c.store_id,
        ),
    )
    return out
