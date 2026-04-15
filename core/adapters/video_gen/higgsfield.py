"""HiggsfieldAdapter — Higgsfield AI text→video generator.

Higgsfield (https://higgsfield.ai) specialises in product-in-
scene / lifestyle AI video — the kind of clip a dropshipper
needs for Meta/TikTok ads where the product must appear in a
believable environment (a kitchen gadget on a counter, a fitness
product in a gym). $9/mo starter tier makes it the cheapest
premium AI video source — primary AI path in the ShopAI stack.

Higgsfield's render pipeline is asynchronous: ``VIDEO_GENERATE``
enqueues a job and returns a ``job_id`` + ``status=processing``;
callers poll ``VIDEO_GET_STATUS`` until ``status=ready``, at
which point ``video_url`` is populated.

Auth: ``X-API-Key: <HIGGSFIELD_API_KEY>`` header (not Bearer).

Endpoints (as of 2026-Q1 public docs):

  * ``POST /v1/videos/generate``    — enqueue render job
  * ``GET  /v1/videos/{job_id}``    — poll job status

This adapter is best-effort schema-tolerant: Higgsfield has
iterated on response shapes, so the extraction logic accepts
several envelope variants.
"""
from __future__ import annotations

from typing import Any

from ..base import AdapterResult, Capability
from ._base import VideoGenBaseAdapter


class HiggsfieldAdapter(VideoGenBaseAdapter):
    name = "higgsfield"
    base_url = "https://api.higgsfield.ai/v1"
    config_alias = "higgsfield"

    capabilities = {
        Capability.VIDEO_GENERATE,
        Capability.VIDEO_GET_STATUS,
    }

    priority = 85
    # Amortised per-render cost on the starter tier. Each render
    # is typically 5-8 seconds long; $9/mo gets ~100 renders.
    cost_per_call = 0.09

    kind = "ai"
    requires_key = True
    # AI renders are slow. Give the HTTP call 90s to return the
    # job ID / poll result; the *render* itself is async.
    timeout = 90.0

    def _auth_headers(self) -> dict[str, str]:
        return {
            "X-API-Key": self._api_key(),
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
        duration = int(params.get("duration_seconds", 6) or 6)
        aspect_ratio = str(params.get("aspect_ratio", "9:16") or "9:16")
        style = str(params.get("style", "") or "")

        url = f"{self.base_url}/videos/generate"
        body: dict[str, Any] = {
            "prompt": prompt,
            "duration": duration,
            "aspect_ratio": aspect_ratio,
        }
        if style:
            body["style"] = style

        raw = self._http_request("POST", url, body=body)
        record = _extract_higgsfield_job(raw, prompt=prompt)
        return self._build_job_response(
            capability, record, prompt=prompt, raw=raw,
        )

    # ── Status ────────────────────────────────────────────────

    def _do_get_status(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        self._validate_get_status(params)
        job_id = str(params["job_id"])
        url = f"{self.base_url}/videos/{job_id}"
        raw = self._http_request("GET", url)
        record = _extract_higgsfield_job(raw)
        # Carry the job_id through so the engine can re-poll
        # without re-parsing.
        if not record.get("clip_id"):
            record["clip_id"] = job_id
        return self._build_job_response(
            capability, record, raw=raw,
        )


def _extract_higgsfield_job(
    raw: Any, *, prompt: str = "",
) -> dict[str, Any]:
    """Pull a single job record out of Higgsfield's response.

    Schema drift tolerated — the actual shape has been observed
    as any of:

        {"job": {...}}
        {"data": {...}}
        {"id": "...", "status": "..."}
    """
    if not isinstance(raw, dict):
        return {"status": "failed", "prompt": prompt}

    payload = raw
    for key in ("job", "data", "video", "result"):
        nested = raw.get(key)
        if isinstance(nested, dict):
            payload = nested
            break

    status_raw = str(payload.get("status", "") or "").lower()
    # Map Higgsfield's vocabulary onto our 3-state model.
    if status_raw in ("done", "ready", "succeeded", "completed"):
        status = "ready"
    elif status_raw in ("failed", "error", "cancelled"):
        status = "failed"
    else:
        status = "processing"

    # video_url may live at top-level or under an "output"/"url" nest.
    video_url = (
        payload.get("video_url")
        or payload.get("url")
        or ""
    )
    output = payload.get("output")
    if not video_url and isinstance(output, dict):
        video_url = output.get("video_url") or output.get("url") or ""
    if not video_url and isinstance(output, list) and output:
        first = output[0]
        if isinstance(first, dict):
            video_url = first.get("video_url") or first.get("url") or ""
        elif isinstance(first, str):
            video_url = first

    thumb = (
        payload.get("thumbnail_url")
        or payload.get("thumbnail")
        or (isinstance(output, dict) and output.get("thumbnail_url"))
        or ""
    )

    return {
        "clip_id":       str(payload.get("id") or payload.get("job_id") or ""),
        "source":        "higgsfield",
        "kind":          "ai",
        "status":        status,
        "video_url":     str(video_url or ""),
        "thumbnail_url": str(thumb or ""),
        "duration_seconds": payload.get("duration", 0),
        "width":         payload.get("width", 0),
        "height":        payload.get("height", 0),
        "format":        "mp4",
        "license":       "proprietary",
        "cost_usd":      0.0,
        "prompt":        prompt or str(payload.get("prompt", "") or ""),
        "raw_url":       str(payload.get("dashboard_url", "") or ""),
    }
