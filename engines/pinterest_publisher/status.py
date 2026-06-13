"""Pinterest readiness diagnostic.

Three gates: adapter registered + credentials present +
live auth probe succeeds.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class PinterestStatus:
    adapter_registered: bool = False
    credentials_present: bool = False
    auth_verified: bool = False
    username: str = ""
    account_type: str = ""
    detail: str = ""

    @property
    def ready(self) -> bool:
        return (
            self.adapter_registered
            and self.credentials_present
        )


def get_status(*, skip_live: bool = False) -> PinterestStatus:
    """Read-only readiness check.

    skip_live=True omits the auth_verify HTTP probe (fast path
    for CLIs that just want adapter + creds state).
    """
    status = PinterestStatus()

    # Auto-bootstrap the social family (idempotent) so a
    # cold-process probe doesn't miss the adapter.
    try:
        from core.adapters.social.bootstrap import register_all
        register_all()
    except Exception:  # noqa: BLE001
        pass

    # Adapter registered?
    try:
        from core.adapters.router import get_registry
        from core.adapters.base import Capability
        reg = get_registry()
        # configured_only=False so we detect REGISTERED
        # adapter even when its env var hasn't been wired -- the
        # diagnostic distinguishes the two states explicitly.
        adapters = reg.find_by_capability(
            Capability.SOCIAL_VERIFY_AUTH,
            configured_only=False,
        ) or []
        status.adapter_registered = any(
            "pinterest" in str(getattr(a, "name", "")).lower()
            for a in adapters
        )
    except Exception:  # noqa: BLE001
        pass

    # Credentials present?
    status.credentials_present = bool(
        os.environ.get("PINTEREST_ACCESS_TOKEN"),
    )

    # Compose detail.
    if not status.adapter_registered:
        status.detail = (
            "adapter not bootstrapped "
            "(call core.adapters.social.bootstrap.register_all)"
        )
    elif not status.credentials_present:
        status.detail = "missing PINTEREST_ACCESS_TOKEN"
    elif skip_live:
        status.detail = "credentials present (live probe skipped)"
    else:
        status.detail = "ready (running live auth probe...)"

    # Live auth probe.
    if (
        not skip_live
        and status.adapter_registered
        and status.credentials_present
    ):
        try:
            from core.adapters.router import get_router
            from core.adapters.base import Capability
            router = get_router()
            result = router.execute(
                Capability.SOCIAL_VERIFY_AUTH, {},
            )
            if getattr(result, "ok", False):
                data = getattr(result, "data", None) or {}
                status.auth_verified = True
                status.username = str(data.get("username", ""))
                status.account_type = str(
                    data.get("account_type", ""),
                )
                status.detail = (
                    f"ready (auth verified, user="
                    f"{status.username or '?'})"
                )
            else:
                err = getattr(result, "error", "") or ""
                status.detail = (
                    f"creds present but auth failed: "
                    f"{err[:120]}"
                )
        except Exception as exc:  # noqa: BLE001
            status.detail = (
                f"creds present but auth probe raised: "
                f"{type(exc).__name__}"
            )
    return status
