"""TikTok readiness diagnostic."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class TikTokStatus:
    adapter_registered: bool = False
    credentials_present: bool = False
    business_id_present: bool = False
    auth_verified: bool = False
    username: str = ""
    business_id: str = ""
    detail: str = ""

    @property
    def ready(self) -> bool:
        return (
            self.adapter_registered
            and self.credentials_present
            and self.business_id_present
        )


def get_status(*, skip_live: bool = False) -> TikTokStatus:
    status = TikTokStatus()

    # Auto-bootstrap social family (idempotent).
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
        adapters = reg.find_by_capability(
            Capability.SOCIAL_CREATE_POST,
            configured_only=False,
        ) or []
        status.adapter_registered = any(
            "tiktok" in str(getattr(a, "name", "")).lower()
            for a in adapters
        )
    except Exception:  # noqa: BLE001
        pass

    # Credentials present?
    status.credentials_present = bool(
        os.environ.get("TIKTOK_ACCESS_TOKEN"),
    )
    status.business_id_present = bool(
        os.environ.get("TIKTOK_BUSINESS_ID"),
    )

    # Compose detail.
    missing = []
    if not status.adapter_registered:
        missing.append("adapter")
    if not status.credentials_present:
        missing.append("TIKTOK_ACCESS_TOKEN")
    if not status.business_id_present:
        missing.append("TIKTOK_BUSINESS_ID")

    if missing:
        status.detail = "missing: " + ", ".join(missing)
    elif skip_live:
        status.detail = "credentials present (live probe skipped)"
    else:
        status.detail = "ready (running live auth probe...)"

    # Live auth probe.
    if not skip_live and status.ready:
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
                status.business_id = str(
                    data.get("business_id", ""),
                )
                status.detail = (
                    f"ready (verified, user="
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
