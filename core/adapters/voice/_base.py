"""VoiceBaseAdapter -- shared base for voice / TTS adapters.

Voice adapters wrap text-to-speech APIs. The primary
capability is VOICE_TEXT_TO_SPEECH (raw text in, audio
bytes / URL out). Some vendors also expose VOICE_LIST_VOICES
for catalogue selection.

Normalised TTS response::

    {
        "audio_bytes":   b"...",          # raw audio (MP3 by default)
        "audio_url":     "...",            # set when vendor returns URL
        "audio_format":  "mp3",
        "voice_id":      "...",            # echoed from request
        "duration_secs": 0.0,              # best-effort estimate
        "char_count":    0,                # billing-relevant
    }
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from ..base import (
    AdapterCategory,
    BaseAdapter,
    Capability,
)
from .._per_store_credentials import (
    resolve_per_store as _resolve_per_store,
)
from ..config import get_config
from ..errors import (
    AdapterAuthError,
    AdapterError,
    AdapterNotConfigured,
    AdapterRateLimited,
    AdapterTimeout,
    AdapterUnavailable,
    AdapterValidationError,
)

try:
    import requests as _requests
    _REQUESTS_AVAILABLE = True
except ImportError:  # pragma: no cover
    _requests = None  # type: ignore[assignment]
    _REQUESTS_AVAILABLE = False

logger = get_logger("adapters.voice")


_DEFAULT_TIMEOUT = 60.0
# Most TTS APIs cap a single call at ~5k chars. Caller
# should chunk longer scripts manually.
_MAX_CHARS_PER_CALL = 5000


class VoiceBaseAdapter(BaseAdapter):
    """Abstract base for every voice / TTS adapter.

    Concrete adapters MUST set:
      * ``name``         -- registry key
      * ``base_url``     -- vendor API root
      * ``config_alias`` -- env alias for the API key
      * ``capabilities`` -- subset of VOICE_* it implements
    """

    category = AdapterCategory.VOICE
    capabilities: set[Capability] = set()

    base_url: str = ""
    config_alias: str = ""
    timeout: float = _DEFAULT_TIMEOUT
    cost_per_call: float = 0.0
    priority: int = 50
    requires_key: bool = True

    # ── Configuration ──────────────────────────────────────────

    def is_configured(self) -> bool:
        if not _REQUESTS_AVAILABLE:
            return False
        if not self.base_url:
            return False
        if not self.requires_key:
            return True
        if not self.config_alias:
            return False
        return bool((_resolve_per_store(self.config_alias) or get_config().get(self.config_alias)))

    def _api_key(self) -> str:
        if not self.requires_key:
            return ""
        key = (_resolve_per_store(self.config_alias) or get_config().get(self.config_alias))
        if not key:
            env = get_config().env_var_for(self.config_alias)
            raise AdapterNotConfigured(
                self.name,
                f"missing API key (set ${env or self.config_alias})",
            )
        return key

    # ── Dispatch ───────────────────────────────────────────────

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability not in self.capabilities:
            raise AdapterValidationError(
                self.name,
                f"{self.name} does not implement {capability.value}",
            )
        if capability == Capability.VOICE_TEXT_TO_SPEECH:
            self._validate_tts(params)
            return self._do_tts(capability, params)
        if capability == Capability.VOICE_LIST_VOICES:
            return self._do_list_voices(capability, params)
        raise AdapterValidationError(
            self.name,
            f"unsupported capability: {capability.value}",
        )

    # ── Validation ─────────────────────────────────────────────

    def _validate_tts(self, params: dict[str, Any]) -> None:
        text = params.get("text")
        if not text or not isinstance(text, str):
            raise AdapterValidationError(
                self.name, "'text' is required for voice TTS",
            )
        if len(text) > _MAX_CHARS_PER_CALL:
            raise AdapterValidationError(
                self.name,
                f"'text' exceeds {_MAX_CHARS_PER_CALL} char "
                "per-call cap -- chunk client-side",
            )
        voice_id = params.get("voice_id")
        if voice_id is not None and not isinstance(voice_id, str):
            raise AdapterValidationError(
                self.name, "'voice_id' must be a string",
            )

    # ── Vendor hooks (override in subclass) ────────────────────

    def _do_tts(
        self, capability: Capability, params: dict[str, Any],
    ) -> Any:
        raise NotImplementedError(
            f"{type(self).__name__}._do_tts must be implemented",
        )

    def _do_list_voices(
        self, capability: Capability, params: dict[str, Any],
    ) -> Any:
        raise NotImplementedError(
            f"{type(self).__name__}._do_list_voices "
            "must be implemented",
        )

    # ── HTTP helpers ───────────────────────────────────────────

    def _handle_http_error(
        self,
        status_code: int,
        body: str,
    ) -> AdapterError:
        snippet = (body or "")[:200]
        if status_code in (401, 403):
            return AdapterAuthError(
                self.name,
                f"vendor rejected credentials ({status_code}): "
                f"{snippet}",
            )
        if status_code == 429:
            return AdapterRateLimited(
                self.name, f"rate limit ({status_code})",
            )
        if 500 <= status_code < 600:
            return AdapterUnavailable(
                self.name, f"vendor 5xx ({status_code}): {snippet}",
            )
        return AdapterError(
            self.name, f"HTTP {status_code}: {snippet}",
        )
