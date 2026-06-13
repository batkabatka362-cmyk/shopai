"""Diagnostic helpers: are the ads platforms wired?

Each platform has 3 readiness gates:
  - adapter_registered: bootstrap added the adapter to the router
  - credentials_present: env / config has the required tokens
  - account_resolved: an account_id is set for billing scoping

Returns a structured report per-platform that the CLI renders.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PlatformStatus:
    platform: str
    adapter_registered: bool = False
    credentials_present: bool = False
    account_resolved: bool = False
    detail: str = ""
    env_vars_needed: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return (
            self.adapter_registered
            and self.credentials_present
            and self.account_resolved
        )


_PLATFORM_CHECKS: dict[str, dict[str, Any]] = {
    "meta": {
        "capability": "ADS_CREATE_CAMPAIGN",
        "env_token": "META_ADS_ACCESS_TOKEN",
        "env_account": "META_ADS_ACCOUNT_ID",
        "config_token": "meta_ads_access_token",
        "config_account": "meta_ads_account_id",
    },
    "google": {
        "capability": "ADS_CREATE_CAMPAIGN",
        "env_token": "GOOGLE_ADS_ACCESS_TOKEN",
        "env_account": "GOOGLE_ADS_CUSTOMER_ID",
        "config_token": "google_ads_access_token",
        "config_account": "google_ads_customer_id",
    },
}


def _check_adapter_registered(platform: str) -> bool:
    """Probe the router for an adapter that claims the
    ADS_CREATE_CAMPAIGN capability with a name matching the
    platform."""
    try:
        from core.adapters.router import get_registry
        from core.adapters.base import Capability
        reg = get_registry()
        adapters = reg.adapters_for_capability(
            Capability.ADS_CREATE_CAMPAIGN,
        ) or []
        for a in adapters:
            if platform in str(getattr(a, "name", "")).lower():
                return True
    except Exception:  # noqa: BLE001
        return False
    return False


def _check_credentials(platform: str) -> tuple[bool, bool]:
    """Return (token_present, account_present) by checking both
    env vars and the adapter config."""
    cfg = _PLATFORM_CHECKS.get(platform) or {}
    token_present = bool(
        os.environ.get(cfg.get("env_token", ""))
    )
    account_present = bool(
        os.environ.get(cfg.get("env_account", ""))
    )
    if not token_present or not account_present:
        try:
            from core.adapters.config import get_config
            adapter_cfg = get_config()
            token_present = token_present or bool(
                adapter_cfg.get(cfg.get("config_token", ""))
            )
            account_present = account_present or bool(
                adapter_cfg.get(cfg.get("config_account", ""))
            )
        except Exception:  # noqa: BLE001
            pass
    return token_present, account_present


def get_platform_status(platform: str) -> PlatformStatus:
    """Single-platform readiness report."""
    platform = platform.lower()
    if platform not in _PLATFORM_CHECKS:
        return PlatformStatus(
            platform=platform,
            detail=f"unknown platform '{platform}'",
        )

    cfg = _PLATFORM_CHECKS[platform]
    adapter_ok = _check_adapter_registered(platform)
    token_ok, account_ok = _check_credentials(platform)

    missing_envs = []
    if not token_ok:
        missing_envs.append(cfg["env_token"])
    if not account_ok:
        missing_envs.append(cfg["env_account"])

    if not adapter_ok:
        detail = "adapter not bootstrapped"
    elif not token_ok:
        detail = f"missing token (set {cfg['env_token']})"
    elif not account_ok:
        detail = f"missing account_id (set {cfg['env_account']})"
    else:
        detail = "ready to launch"

    return PlatformStatus(
        platform=platform,
        adapter_registered=adapter_ok,
        credentials_present=token_ok,
        account_resolved=account_ok,
        detail=detail,
        env_vars_needed=missing_envs,
    )


def get_all_status() -> dict[str, PlatformStatus]:
    """All-platform readiness rollup. Returns a dict keyed by
    platform name."""
    return {
        p: get_platform_status(p)
        for p in _PLATFORM_CHECKS
    }
