"""ReplicateAdapter — open-source AI video via Replicate.com.

Replicate (https://replicate.com) hosts open-source text→video
models (Wan, Mochi, CogVideoX, Stable Video Diffusion) on a
pay-per-second-of-compute basis. Typical costs are $0.05-$0.30
per render — cheaper than most dedicated AI-video providers,
making it a budget-conscious fallback when the Higgsfield
quota is exhausted.

Auth: ``Authorization: Token <REPLICATE_API_TOKEN>`` header
(NOT Bearer). The default model is a fast public text→video
checkpoint; callers can override via ``params["model"]`` with a
``owner/model:version`` identifier.

Async flow: ``POST /predictions`` returns an ``id`` and
``status="starting"``; ``GET /predictions/{id}`` polls status.
"""
from __future__ import annotations

from typing import Any

from ..base import AdapterResult, Capability
from ._base import VideoGenBaseAdapter


# A reasonable default text→video model. Operators can override
# per-call via params["model"] to pin a specific version or
# try different checkpoints.
_DEFAULT_MODEL = (
    "anotherjesse/zeroscope-v2-xl:"
    "9f747673945c62801b13b84701c783929c0ee784e4748ec062204894dda1a351"
)


class ReplicateAdapter(VideoGenBaseAdapter):
    name = "replicate"
    base_url = "https://api.replicate.com/v1"
    config_alias = "replicate"

    capabilities = {
        Capability.VIDEO_GENERATE,
        Capability.VIDEO_GET_STATUS,
    }

    # Lower priority than Higgsfield — output quality is more
    # variable (depends on the model), but it's dramatically
    # cheaper so it wins on budget-constrained runs.
    priority = 70
    cost_per_call = 0.15

    kind = "ai"
    requires_key = True
    timeout = 90.0

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Token {self._api_key()}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "ShopAI-VideoGen/1.0",
        }

    # ── Generate ───────────────────────────────────────────────

    def _do_generate(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        self._validate_generate(params)
        prompt = str(params["prompt"])
        model = str(params.get("model", "") or _DEFAULT_MODEL)
        duration = int(params.get("duration_seconds", 0) or 0)

        # Replicate takes the version (the sha after the colon)
        # as a separate field. Format: "owner/name:version".
        if ":" in model:
            _, version = model.split(":", 1)
        else:
            # Assume the caller passed a raw version hash.
            version = model

        url = f"{self.base_url}/predictions"
        body: dict[str, Any] = {
            "version": version,
            "input": {"prompt": prompt},
        }
        if duration:
            body["input"]["num_frames"] = max(8, duration * 8)

        raw = self._http_request("POST", url, body=body)
        record = _extract_replicate_job(raw, prompt=prompt)
        return self._build_job_response(
            capability, record, prompt=prompt, raw=raw,
        )

    # ── Status ────────────────────────────────────────────────

    def _do_get_status(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        self._validate_get_status(params)
        job_id = str(params["job_id"])
        url = f"{self.base_url}/predictions/{job_id}"
        raw = self._http_request("GET", url)
        record = _extract_replicate_job(raw)
        if not record.get("clip_id"):
            record["clip_id"] = job_id
        return self._build_job_response(
            capability, record, raw=raw,
        )


def _extract_replicate_job(
    raw: Any, *, prompt: str = "",
) -> dict[str, Any]:
    """Map Replicate's prediction payload to the normalised job record."""
    if not isinstance(raw, dict):
        return {"status": "failed", "prompt": prompt}

    status_raw = str(raw.get("status", "") or "").lower()
    # Replicate states: starting, processing, succeeded, failed,
    # canceled. Map onto our 3-state model.
    if status_raw in ("succeeded",):
        status = "ready"
    elif status_raw in ("failed", "canceled"):
        status = "failed"
    else:
        status = "processing"

    # ``output`` for video models is usually a URL string or a
    # list of frame URLs (grid). Single URL = MP4; list = we take
    # the first entry (per-model convention varies).
    output = raw.get("output")
    video_url = ""
    if isinstance(output, str):
        video_url = output
    elif isinstance(output, list) and output:
        first = output[0]
        if isinstance(first, str):
            video_url = first
        elif isinstance(first, dict):
            video_url = first.get("url", "") or ""

    return {
        "clip_id":       str(raw.get("id", "") or ""),
        "source":        "replicate",
        "kind":          "ai",
        "status":        status,
        "video_url":     str(video_url or ""),
        "thumbnail_url": "",
        "duration_seconds": 0,
        "width":         0,
        "height":        0,
        "format":        "mp4",
        "license":       "proprietary",
        "cost_usd":      0.0,
        "prompt":        prompt or str((raw.get("input") or {}).get("prompt") or ""),
        "raw_url":       str((raw.get("urls") or {}).get("get", "") or ""),
    }
