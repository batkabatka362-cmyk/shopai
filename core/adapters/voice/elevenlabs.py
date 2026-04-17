"""ElevenLabsAdapter — ElevenLabs text-to-speech API.

ElevenLabs produces the most natural-sounding AI voices
available. Use cases for Shopify stores:

  * **Product narration** — generate audio descriptions for
    accessibility and product pages
  * **Customer support** — voice responses for IVR / phone bots
  * **Marketing** — voiceovers for video ads and social media

Capabilities:
  * VOICE_TEXT_TO_SPEECH — convert text to audio (mp3/wav)
  * VOICE_LIST_VOICES   — list available voices

Authentication: ``xi-api-key`` header.
Free tier: 10,000 characters/month.
Pricing: from $5/month for 30K characters.

Reference: https://elevenlabs.io/docs/api-reference
"""
from __future__ import annotations

import base64
from typing import Any

from ..base import AdapterResult, Capability
from ..errors import AdapterValidationError
from ._base import VoiceBaseAdapter


class ElevenLabsAdapter(VoiceBaseAdapter):
    name = "elevenlabs"
    base_url = "https://api.elevenlabs.io/v1"
    config_alias = "elevenlabs"

    priority = 90
    cost_per_call = 0.0  # Free tier; paid is per-character

    # ── Text to speech ─────────────────────────────────────────

    def _do_text_to_speech(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        text = params.get("text")
        if not text:
            raise AdapterValidationError(
                self.name, "'text' is required",
            )

        voice_id = params.get(
            "voice_id", "21m00Tcm4TlvDq8ikWAM",  # Rachel (default)
        )
        model_id = params.get("model_id", "eleven_monolingual_v1")
        output_format = params.get("output_format", "mp3_44100_128")

        url = (
            f"{self.base_url}/text-to-speech/{voice_id}"
            f"?output_format={output_format}"
        )
        body = {
            "text": text,
            "model_id": model_id,
        }
        if params.get("voice_settings"):
            body["voice_settings"] = params["voice_settings"]
        else:
            body["voice_settings"] = {
                "stability": params.get("stability", 0.5),
                "similarity_boost": params.get("similarity_boost", 0.75),
            }

        # Stream audio response
        response = self._http_request(
            "POST", url, body=body, stream=True,
        )

        # Read audio bytes
        audio_bytes = response.content
        audio_b64 = base64.b64encode(audio_bytes).decode("ascii")

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "audio_base64": audio_b64,
                "format": output_format,
                "voice_id": voice_id,
                "characters": len(text),
                "size_bytes": len(audio_bytes),
            },
        )

    # ── List voices ────────────────────────────────────────────

    def _do_list_voices(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        url = f"{self.base_url}/voices"
        raw = self._http_request("GET", url)

        voices = []
        for v in raw.get("voices", []):
            voices.append({
                "voice_id": v.get("voice_id", ""),
                "name": v.get("name", ""),
                "category": v.get("category", ""),
                "labels": v.get("labels", {}),
                "preview_url": v.get("preview_url", ""),
            })

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={"voices": voices, "count": len(voices)},
            raw=raw,
        )
