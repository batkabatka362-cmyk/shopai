"""Gemini multimodal image analysis.

Given a product image URL, ask Gemini to score:

    quality          — 0-100 overall readiness for ads
    lighting         — 0-100 exposure + contrast
    background       — "clean" | "busy" | "missing"
    subject_centered — bool
    issues           — list of short problem strings
    hero_suitable    — bool (good enough for a primary ad creative)

Used by MediaStep / CreativeStep to block bad imagery before it ever
reaches Meta Ads. Gemini's free-tier supports image analysis at no
cost; request shape mirrors the :generateContent REST call.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

from utils.logger import get_logger


logger = get_logger("adapters.image.vision")


_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-flash-latest:generateContent"
)
_MAX_IMAGE_BYTES = 3_500_000   # 3.5 MB — well under Gemini's 20 MB limit


def is_configured() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))


def analyze(image_url: str) -> dict[str, Any]:
    """Return a quality report for *image_url*. Empty dict on any
    failure (network, unconfigured, un-parseable JSON)."""
    if not image_url or not image_url.startswith(("http://", "https://")):
        return {}
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return {}

    img_bytes = _download(image_url)
    if not img_bytes:
        return {}
    mime = _guess_mime(image_url, img_bytes)

    prompt = (
        "You are an e-commerce product-image QA agent. Look at this "
        "image and reply with a compact JSON object. Do not include any "
        "text outside the JSON. Fields:\n"
        '  quality: integer 0-100 (overall readiness for paid ads)\n'
        '  lighting: integer 0-100\n'
        '  background: "clean" | "busy" | "missing"\n'
        '  subject_centered: boolean\n'
        '  hero_suitable: boolean\n'
        '  issues: array of <=5 short strings describing problems\n'
        '  description: one-sentence shoppable description\n'
    )

    body = json.dumps({
        "contents": [{
            "parts": [
                {"text": prompt},
                {"inline_data": {
                    "mime_type": mime,
                    "data": base64.b64encode(img_bytes).decode("ascii"),
                }},
            ],
        }],
        "generationConfig": {
            "temperature": 0.1,
            # gemini-flash-latest is a thinking model — thought tokens
            # eat into max_output_tokens before the JSON is emitted,
            # so we need a generous cap (observed ~650 thought tokens).
            "max_output_tokens": 1200,
        },
    }).encode("utf-8")

    req = urllib.request.Request(
        _ENDPOINT,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-goog-api-key": api_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
        logger.debug("vision request failed: %s", exc)
        return {}

    text = _extract_text(payload)
    parsed = _parse_json(text)
    if not parsed:
        return {}
    parsed["_url"] = image_url
    return parsed


def analyze_batch(urls: list[str], limit: int = 8) -> list[dict[str, Any]]:
    """Analyse up to *limit* images, preserving order. Blocks serially —
    a parallel impl would save wall-clock time but multiply the free-tier
    quota cost."""
    out: list[dict[str, Any]] = []
    for u in urls[:limit]:
        report = analyze(u)
        if report:
            out.append(report)
    return out


# ── Helpers ─────────────────────────────────────────────────

def _download(url: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "ShopAI/1.0 (+https://github.com/batkabatka362-cmyk/shopai)",
            "Accept": "image/*",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read(_MAX_IMAGE_BYTES + 1)
    except (urllib.error.URLError, urllib.error.HTTPError) as exc:
        logger.debug("image download failed (%s): %s", url, exc)
        return b""
    if not data:
        return b""
    if len(data) > _MAX_IMAGE_BYTES:
        # Silently skip oversized images — reduce them upstream
        logger.debug("image too large (%d bytes): %s", len(data), url)
        return b""
    return data


def _guess_mime(url: str, data: bytes) -> str:
    ext = url.lower().rsplit(".", 1)[-1].split("?", 1)[0]
    if ext in ("jpg", "jpeg"):
        return "image/jpeg"
    if ext == "png":
        return "image/png"
    if ext == "webp":
        return "image/webp"
    if ext == "gif":
        return "image/gif"
    # Peek the magic bytes
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"RIFF") and b"WEBP" in data[:32]:
        return "image/webp"
    return "image/jpeg"


def _extract_text(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates") or []
    for cand in candidates:
        for part in (cand.get("content") or {}).get("parts") or []:
            t = part.get("text")
            if t:
                return t
    return ""


def _parse_json(text: str) -> dict[str, Any]:
    if not text:
        return {}
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return {}
    try:
        obj = json.loads(m.group(0))
    except (json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(obj, dict):
        return {}
    # Coerce numeric fields
    for k in ("quality", "lighting"):
        try:
            obj[k] = int(obj.get(k) or 0)
        except (TypeError, ValueError):
            obj[k] = 0
    for k in ("subject_centered", "hero_suitable"):
        obj[k] = bool(obj.get(k))
    obj["issues"] = [str(i)[:120] for i in (obj.get("issues") or []) if i][:5]
    return obj
