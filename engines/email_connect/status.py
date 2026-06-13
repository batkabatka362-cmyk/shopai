"""Diagnostic: which email ESP providers are wired."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class ProviderStatus:
    provider: str
    env_var: str
    adapter_wired: bool = False  # does an adapter module exist?
    credentials_present: bool = False  # is the env var set?
    detail: str = ""

    @property
    def ready(self) -> bool:
        return self.adapter_wired and self.credentials_present


# Provider -> (env_var, adapter_module_path)
# A module-path of "" means no adapter implemented yet (the env-
# var slot exists in core/adapters/config.py for future wiring).
_PROVIDERS: dict[str, tuple[str, str]] = {
    "brevo":    ("BREVO_API_KEY",    "core.adapters.email.brevo"),
    "resend":   ("RESEND_API_KEY",   "core.adapters.email.resend"),
    "sendgrid": ("SENDGRID_API_KEY", ""),
    "klaviyo":  ("KLAVIYO_API_KEY",  ""),
}


def _check_adapter_wired(module_path: str) -> bool:
    if not module_path:
        return False
    try:
        __import__(module_path)
        return True
    except Exception:  # noqa: BLE001
        return False


def get_provider_status(provider: str) -> ProviderStatus:
    provider = (provider or "").lower()
    if provider not in _PROVIDERS:
        return ProviderStatus(
            provider=provider,
            env_var="",
            detail=f"unknown provider '{provider}'",
        )
    env_var, module_path = _PROVIDERS[provider]
    adapter_ok = _check_adapter_wired(module_path)
    key_present = bool(os.environ.get(env_var))

    if not adapter_ok and not key_present:
        detail = f"no adapter + no {env_var}"
    elif not adapter_ok:
        detail = (
            f"key set but no adapter wired yet "
            f"(env var reserved at core/adapters/config.py)"
        )
    elif not key_present:
        detail = f"missing {env_var}"
    else:
        detail = "ready to send"

    return ProviderStatus(
        provider=provider,
        env_var=env_var,
        adapter_wired=adapter_ok,
        credentials_present=key_present,
        detail=detail,
    )


def get_all_status() -> dict[str, ProviderStatus]:
    return {p: get_provider_status(p) for p in _PROVIDERS}
