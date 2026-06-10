"""ElevenLabsAdapter -- AI voice synthesis (text-to-speech).

ElevenLabs (https://elevenlabs.io) is the canonical voice
source for ShopAI's cold-start ad-creative pipeline.
Combine a Pexels stock clip with an ElevenLabs voiceover
and the per-video creative cost is ~$0.20-0.50 (TTS only).

The config alias ``elevenlabs`` was already registered
in core.adapters.config.ENV_ALIASES + the cold-start
orchestrator references ElevenLabs by name, but pre-fix
no adapter existed. An operator setting ELEVENLABS_API_KEY
would see api-status mark the cold_start category as
ready but no engine could actually generate voiceover --
ad_creative_generator would emit script-only output.

W963-106 closes the gap.

Auth: ``xi-api-key`` header (NOT Bearer). Single API
token; operator generates from ElevenLabs Settings ->
API Keys.

Endpoints:
  * POST /v1/text-to-speech/{voice_id} -- synthesize
  * GET  /v1/voices                     -- list catalogue

Free tier: 10,000 characters/month, ~10 minutes of audio.
Paid plans from $5/month for 30k chars.

Default voice: ``EXAVITQu4vr4xnSDxMaL`` (Sarah, English
female, broad use). Operators override per-call via
params["voice_id"] for product-niche fit.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from ..base import AdapterResult, Capability
from ..errors import AdapterError
from ._base import VoiceBaseAdapter

try:
    import requests as _requests
    _REQUESTS_AVAILABLE = True
except ImportError:  # pragma: no cover
    _requests = None  # type: ignore[assignment]
    _REQUESTS_AVAILABLE = False

logger = get_logger("adapters.voice.elevenlabs")


# Default voice -- "Sarah" (broad-use English female).
# Operators override per-call via params["voice_id"].
_DEFAULT_VOICE_ID = "EXAVITQu4vr4xnSDxMaL"
# eleven_multilingual_v2: best quality/cost ratio. Other
# options: eleven_turbo_v2_5 (faster, lower quality),
# eleven_v3 (highest quality, paid-only).
_DEFAULT_MODEL_ID = "eleven_multilingual_v2"


class ElevenLabsAdapter(VoiceBaseAdapter):
    """ElevenLabs text-to-speech adapter."""

    name = "elevenlabs"
    base_url = "https://api.elevenlabs.io/v1"
    config_alias = "elevenlabs"

    capabilities = {
        Capability.VOICE_TEXT_TO_SPEECH,
        Capability.VOICE_LIST_VOICES,
    }

    priority = 90
    # Free tier: ~$0.30/1000 chars on paid plans. Average
    # voiceover script is ~150-200 chars (~30 sec).
    cost_per_call = 0.06
    requires_key = True

    def _auth_headers(self) -> dict[str, str]:
        """ElevenLabs uses xi-api-key, not Bearer."""
        return {
            "xi-api-key": self._api_key(),
            "Accept": "application/json",
            "User-Agent": "ShopAI-Voice/1.0",
        }

    # ── TTS ────────────────────────────────────────────────────

    def _do_tts(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        text = str(params["text"])
        voice_id = str(
            params.get("voice_id") or _DEFAULT_VOICE_ID,
        )
        model_id = str(
            params.get("model_id") or _DEFAULT_MODEL_ID,
        )
        # Voice stability + similarity_boost: ElevenLabs
        # defaults are 0.5 / 0.75. Higher stability =
        # more monotone; higher similarity = closer to
        # reference voice. Caller can override via
        # voice_settings dict.
        voice_settings = params.get("voice_settings") or {
            "stability": 0.5,
            "similarity_boost": 0.75,
        }

        url = (
            f"{self.base_url}/text-to-speech/{voice_id}"
        )
        body = {
            "text": text,
            "model_id": model_id,
            "voice_settings": voice_settings,
        }

        if not _REQUESTS_AVAILABLE:
            raise AdapterError(
                self.name,
                "'requests' library not installed",
            )

        try:
            resp = _requests.post(
                url,
                headers={
                    **self._auth_headers(),
                    "Content-Type": "application/json",
                    # Request MP3 audio (44.1kHz, 128kbps).
                    "Accept": "audio/mpeg",
                },
                json=body,
                timeout=self.timeout,
            )
        except Exception as exc:  # noqa: BLE001
            raise AdapterError(
                self.name,
                f"network error: {type(exc).__name__}",
            ) from exc

        if resp.status_code >= 400:
            raise self._handle_http_error(
                resp.status_code, resp.text,
            )

        # Success: body is raw audio bytes (MP3).
        audio_bytes = resp.content
        char_count = len(text)

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "audio_bytes": audio_bytes,
                "audio_url": "",
                "audio_format": "mp3",
                "voice_id": voice_id,
                "model_id": model_id,
                # ElevenLabs doesn't return duration in
                # the response; estimate from char count
                # (avg 14 chars/sec at speaking rate).
                "duration_secs": round(
                    char_count / 14.0, 1,
                ),
                "char_count": char_count,
            },
            cost_usd=float(self.cost_per_call),
            raw={"content_length": len(audio_bytes)},
        )

    # ── List voices ────────────────────────────────────────────

    def _do_list_voices(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        url = f"{self.base_url}/voices"
        if not _REQUESTS_AVAILABLE:
            raise AdapterError(
                self.name, "'requests' library not installed",
            )
        try:
            resp = _requests.get(
                url, headers=self._auth_headers(),
                timeout=self.timeout,
            )
        except Exception as exc:  # noqa: BLE001
            raise AdapterError(
                self.name,
                f"network error: {type(exc).__name__}",
            ) from exc
        if resp.status_code >= 400:
            raise self._handle_http_error(
                resp.status_code, resp.text,
            )
        raw = resp.json() or {}
        voices_raw = raw.get("voices") or []
        voices = [
            {
                "voice_id": v.get("voice_id", ""),
                "name": v.get("name", ""),
                "category": v.get("category", ""),
                "labels": v.get("labels") or {},
                "preview_url": v.get("preview_url", ""),
            }
            for v in voices_raw
            if isinstance(v, dict)
        ]
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "voices": voices,
                "count": len(voices),
            },
            raw=raw,
        )
