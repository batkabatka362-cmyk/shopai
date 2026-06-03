"""Pinterest credential setup helper.

Writes PINTEREST_ACCESS_TOKEN to .env with 0o600 perm hygiene.
Mirrors W963-7 ads_launcher.connect and W963-8 email_connect.
"""
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


def connect_pinterest(
    *,
    access_token: str,
    env_path: str = ".env",
) -> ConnectResult:
    """Save Pinterest access token to .env."""
    if not access_token:
        return ConnectResult(
            success=False,
            detail="access_token is required",
        )

    env_var = "PINTEREST_ACCESS_TOKEN"
    new_value = access_token.strip()

    lines: list[str] = []
    seen = False
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
                if key == env_var:
                    lines.append(f"{env_var}={new_value}")
                    seen = True
                    continue
            lines.append(raw)
    if not seen:
        lines.append(f"{env_var}={new_value}")

    try:
        with open(env_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        try:
            os.chmod(env_path, 0o600)
        except OSError:
            pass
    except OSError as exc:
        return ConnectResult(
            success=False,
            detail=f"write .env failed: {exc}",
        )

    # Make available in current process for same-run probes.
    os.environ[env_var] = new_value

    return ConnectResult(
        success=True,
        detail=(
            f"wrote {env_var} to .env "
            f"(prefix: {new_value[:8]}***)"
        ),
        env_path=env_path,
    )
