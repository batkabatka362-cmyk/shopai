"""Ads credential setup helper.

Writes provider-specific tokens + account IDs to .env with the
same 0o600 perm hygiene as the Shopify auth flow. Returns a
structured result the CLI renders.

The connect step does NOT verify the credentials by calling the
platform API — that's the role of ``shopai ads status`` which
runs after.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ConnectResult:
    platform: str
    success: bool
    detail: str
    env_path: str = ""


_PLATFORM_KEYS: dict[str, dict[str, str]] = {
    "meta": {
        "token_env": "META_ADS_ACCESS_TOKEN",
        "account_env": "META_ADS_ACCOUNT_ID",
    },
    "google": {
        "token_env": "GOOGLE_ADS_ACCESS_TOKEN",
        "account_env": "GOOGLE_ADS_CUSTOMER_ID",
    },
}


def connect_platform(
    *,
    platform: str,
    access_token: str,
    account_id: str,
    env_path: str = ".env",
) -> ConnectResult:
    """Write credentials to .env. Returns success/failure
    + detail."""
    platform = (platform or "").lower()
    if platform not in _PLATFORM_KEYS:
        return ConnectResult(
            platform=platform,
            success=False,
            detail=(
                f"unknown platform '{platform}'. Supported: "
                f"{', '.join(_PLATFORM_KEYS)}"
            ),
        )
    if not access_token or not account_id:
        return ConnectResult(
            platform=platform,
            success=False,
            detail="access_token and account_id are required",
        )

    keys = _PLATFORM_KEYS[platform]
    new_env = {
        keys["token_env"]: access_token.strip(),
        keys["account_env"]: account_id.strip(),
    }

    # Read existing, replace matched lines, append the rest.
    lines: list[str] = []
    seen: set[str] = set()
    if os.path.exists(env_path):
        try:
            existing = open(env_path, encoding="utf-8").read()
        except OSError as exc:
            return ConnectResult(
                platform=platform,
                success=False,
                detail=f"read .env failed: {exc}",
            )
        for raw in existing.splitlines():
            stripped = raw.lstrip()
            if "=" in stripped and not stripped.startswith("#"):
                key = stripped.split("=", 1)[0].strip()
                if key in new_env:
                    lines.append(f"{key}={new_env[key]}")
                    seen.add(key)
                    continue
            lines.append(raw)
    for k, v in new_env.items():
        if k not in seen:
            lines.append(f"{k}={v}")

    try:
        with open(env_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        try:
            os.chmod(env_path, 0o600)
        except OSError:
            pass
    except OSError as exc:
        return ConnectResult(
            platform=platform,
            success=False,
            detail=f"write .env failed: {exc}",
        )

    # Also set in the current process env so a status probe in
    # the SAME run sees the new values.
    for k, v in new_env.items():
        os.environ[k] = v

    return ConnectResult(
        platform=platform,
        success=True,
        detail=(
            f"wrote {len(new_env)} key(s) to .env "
            f"(token prefix: {access_token[:7]}***)"
        ),
        env_path=env_path,
    )
