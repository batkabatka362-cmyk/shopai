"""Email ESP credential setup helper.

Writes the provider's API key to .env with the same 0o600 perm
hygiene as W963-7's ads_launcher.connect. Returns a structured
result the CLI renders.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ConnectResult:
    provider: str
    success: bool
    detail: str
    env_path: str = ""


_PROVIDER_ENV: dict[str, str] = {
    "brevo": "BREVO_API_KEY",
    "resend": "RESEND_API_KEY",
    "sendgrid": "SENDGRID_API_KEY",
    "klaviyo": "KLAVIYO_API_KEY",
}


def connect_provider(
    *,
    provider: str,
    api_key: str,
    env_path: str = ".env",
) -> ConnectResult:
    """Write the provider's API key to .env."""
    provider = (provider or "").lower()
    if provider not in _PROVIDER_ENV:
        return ConnectResult(
            provider=provider, success=False,
            detail=(
                f"unknown provider '{provider}'. Supported: "
                f"{', '.join(_PROVIDER_ENV)}"
            ),
        )
    if not api_key:
        return ConnectResult(
            provider=provider, success=False,
            detail="api_key is required",
        )

    env_var = _PROVIDER_ENV[provider]

    lines: list[str] = []
    seen = False
    if os.path.exists(env_path):
        try:
            existing = open(env_path, encoding="utf-8").read()
        except OSError as exc:
            return ConnectResult(
                provider=provider, success=False,
                detail=f"read .env failed: {exc}",
            )
        for raw in existing.splitlines():
            stripped = raw.lstrip()
            if "=" in stripped and not stripped.startswith("#"):
                key = stripped.split("=", 1)[0].strip()
                if key == env_var:
                    lines.append(f"{env_var}={api_key.strip()}")
                    seen = True
                    continue
            lines.append(raw)
    if not seen:
        lines.append(f"{env_var}={api_key.strip()}")

    try:
        with open(env_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        try:
            os.chmod(env_path, 0o600)
        except OSError:
            pass
    except OSError as exc:
        return ConnectResult(
            provider=provider, success=False,
            detail=f"write .env failed: {exc}",
        )

    # Set in process env so a same-run send-test sees it.
    os.environ[env_var] = api_key.strip()

    return ConnectResult(
        provider=provider, success=True,
        detail=(
            f"wrote {env_var} to .env "
            f"(key prefix: {api_key[:7]}***)"
        ),
        env_path=env_path,
    )
