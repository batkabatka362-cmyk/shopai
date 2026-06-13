"""TikTok credential setup helper."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ConnectResult:
    success: bool
    detail: str
    env_path: str = ""


def connect_tiktok(
    *,
    access_token: str,
    business_id: str,
    env_path: str = ".env",
) -> ConnectResult:
    if not access_token:
        return ConnectResult(
            success=False, detail="access_token is required",
        )
    if not business_id:
        return ConnectResult(
            success=False, detail="business_id is required",
        )

    pairs = {
        "TIKTOK_ACCESS_TOKEN": access_token.strip(),
        "TIKTOK_BUSINESS_ID": business_id.strip(),
    }

    lines: list[str] = []
    seen: set[str] = set()
    if os.path.exists(env_path):
        try:
            existing = open(env_path, encoding="utf-8").read()
        except OSError as exc:
            return ConnectResult(
                success=False,
                detail=f"read .env failed: {exc}",
            )
        for raw in existing.splitlines():
            stripped = raw.lstrip()
            if "=" in stripped and not stripped.startswith("#"):
                key = stripped.split("=", 1)[0].strip()
                if key in pairs:
                    lines.append(f"{key}={pairs[key]}")
                    seen.add(key)
                    continue
            lines.append(raw)
    for k, v in pairs.items():
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
            success=False, detail=f"write .env failed: {exc}",
        )

    # Set in process env so same-run probes see the new values.
    for k, v in pairs.items():
        os.environ[k] = v

    return ConnectResult(
        success=True,
        detail=(
            f"wrote 2 keys to .env "
            f"(token prefix: {access_token[:7]}***)"
        ),
        env_path=env_path,
    )
