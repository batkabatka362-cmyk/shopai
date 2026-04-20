"""fal.ai video router — cost-aware model selection.

Wave D-1 of IMPLEMENTATION_PLAN_2026. Per the 2026 research:
Sora 2 shut down March 24 2026. fal.ai is 30-50% cheaper than
Replicate and hosts Kling 2.6 / Veo 3.1 / Runway Gen-4 / Pika.
Andromeda / Symphony / PMax all reward creative volume — the
cheapest-per-second model that meets a request's quality spec
wins.

This router:
  * Holds a catalogue of models with (model_id, price_per_sec,
    quality_tier, max_duration_s, aspect_ratios).
  * ``route(request)`` picks the cheapest model that meets the
    request's quality_floor + budget + duration + aspect.
  * Enforces an owner-set budget ceiling per SKU per week (env
    ``SHOPAI_VIDEO_BUDGET_SKU_WEEK_USD`` default $10).
  * Records every call + spend in SQLite so ``spent_this_week
    (sku)`` can enforce the cap.
  * HTTP layer injectable — tests run offline.

fal.ai API shape (simplified):
  * POST ``https://fal.run/fal-ai/<model_id>`` with JSON body
  * Auth: ``Authorization: Key <FAL_KEY>``
  * Returns video_url, request_id, timing

Pure stdlib + requests. Thread-safe (RLock). LLM-free.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from utils.logger import get_logger


logger = get_logger("core.adapters.fal.video_router")


_DEFAULT_BASE = "https://fal.run"
_DEFAULT_TIMEOUT = 120.0   # video generation is slow
_ENV_KEY = "FAL_KEY"
_ENV_WEEKLY_CAP = "SHOPAI_VIDEO_BUDGET_SKU_WEEK_USD"
_DEFAULT_WEEKLY_CAP_USD = 10.0


_SCHEMA = """
CREATE TABLE IF NOT EXISTS fal_spend (
    spend_id      TEXT PRIMARY KEY,
    sku           TEXT NOT NULL,
    model_id      TEXT NOT NULL,
    duration_s    REAL NOT NULL,
    cost_usd      REAL NOT NULL,
    created_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fal_spend_sku_ts
    ON fal_spend(sku, created_at);
"""


@dataclass
class VideoModel:
    model_id: str                  # "fal-ai/kling-video/v2.6-turbo"
    quality_tier: str              # "volume" | "hero" | "premium"
    price_per_sec: float
    max_duration_s: float
    aspect_ratios: tuple[str, ...]
    notes: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "quality_tier": self.quality_tier,
            "price_per_sec": round(
                self.price_per_sec, 4,
            ),
            "max_duration_s": self.max_duration_s,
            "aspect_ratios": list(self.aspect_ratios),
            "notes": self.notes,
        }


# April 2026 prices per fal.ai public pricing page
_DEFAULT_CATALOGUE: tuple[VideoModel, ...] = (
    VideoModel(
        model_id="fal-ai/kling-video/v2.6-turbo-pro",
        quality_tier="volume",
        price_per_sec=0.07,
        max_duration_s=10.0,
        aspect_ratios=("9:16", "1:1", "16:9"),
        notes="cheapest volume model; fast render",
    ),
    VideoModel(
        model_id="fal-ai/kling-video/v2.6-standard",
        quality_tier="volume",
        price_per_sec=0.10,
        max_duration_s=10.0,
        aspect_ratios=("9:16", "1:1", "16:9"),
    ),
    VideoModel(
        model_id="fal-ai/runway-gen-4",
        quality_tier="hero",
        price_per_sec=0.15,
        max_duration_s=10.0,
        aspect_ratios=("9:16", "16:9"),
        notes="stylized hero content",
    ),
    VideoModel(
        model_id="fal-ai/veo-3.1",
        quality_tier="premium",
        price_per_sec=0.20,
        max_duration_s=8.0,
        aspect_ratios=("9:16", "16:9"),
        notes="highest fidelity; 4K capable",
    ),
)


@dataclass
class VideoRequest:
    sku: str
    prompt: str
    aspect: str = "9:16"
    duration_s: float = 5.0
    quality_floor: str = "volume"   # or "hero", "premium"
    reference_image_url: str = ""
    seed: int = 0

    def __post_init__(self) -> None:
        if not self.sku:
            raise ValueError("sku required")
        if not self.prompt:
            raise ValueError("prompt required")
        if self.duration_s <= 0:
            raise ValueError("duration_s must be > 0")

    def as_dict(self) -> dict[str, Any]:
        return {
            "sku": self.sku,
            "prompt": self.prompt,
            "aspect": self.aspect,
            "duration_s": self.duration_s,
            "quality_floor": self.quality_floor,
            "reference_image_url": (
                self.reference_image_url
            ),
            "seed": self.seed,
        }


@dataclass
class VideoResult:
    ok: bool
    model_id: str = ""
    video_url: str = ""
    cost_usd: float = 0.0
    duration_s: float = 0.0
    request_id: str = ""
    error: str = ""
    skipped_reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "model_id": self.model_id,
            "video_url": self.video_url,
            "cost_usd": round(self.cost_usd, 4),
            "duration_s": self.duration_s,
            "request_id": self.request_id,
            "error": self.error,
            "skipped_reason": self.skipped_reason,
        }


_QUALITY_ORDER = {
    "volume": 0, "hero": 1, "premium": 2,
}


class FalVideoRouter:
    """Cost-aware fal.ai video generator."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = _DEFAULT_BASE,
        catalogue: tuple[VideoModel, ...] | None = None,
        db_path: str | Path = "data/fal_spend.db",
        http: Any = None,
        weekly_cap_usd: float | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
        now_fn: Any = None,
    ) -> None:
        self._api_key = (
            api_key
            if api_key is not None
            else os.environ.get(_ENV_KEY, "")
        )
        self._base = base_url.rstrip("/")
        self._catalogue = tuple(
            catalogue if catalogue is not None
            else _DEFAULT_CATALOGUE
        )
        if weekly_cap_usd is not None:
            self._cap = float(weekly_cap_usd)
        else:
            try:
                self._cap = float(
                    os.environ.get(
                        _ENV_WEEKLY_CAP,
                        _DEFAULT_WEEKLY_CAP_USD,
                    ),
                )
            except (TypeError, ValueError):
                self._cap = _DEFAULT_WEEKLY_CAP_USD
        self._timeout = float(timeout)
        self._http = http
        self._now_fn = now_fn or time.time
        self._lock = threading.RLock()
        self._path = Path(db_path)
        self._path.parent.mkdir(
            parents=True, exist_ok=True,
        )
        self._conn = sqlite3.connect(
            str(self._path), check_same_thread=False,
        )
        with self._lock:
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def is_available(self) -> bool:
        return bool(self._api_key)

    def _client(self) -> Any:
        if self._http is not None:
            return self._http
        import requests
        return requests

    # ── Selection ────────────────────────────────────────

    def pick_model(
        self, request: VideoRequest,
    ) -> VideoModel | None:
        """Cheapest model meeting quality floor + aspect +
        duration."""
        floor = _QUALITY_ORDER.get(
            request.quality_floor, 0,
        )
        candidates: list[VideoModel] = []
        for m in self._catalogue:
            if (
                _QUALITY_ORDER.get(m.quality_tier, 0)
                < floor
            ):
                continue
            if request.duration_s > m.max_duration_s:
                continue
            if (
                request.aspect
                and request.aspect not in m.aspect_ratios
            ):
                continue
            candidates.append(m)
        if not candidates:
            return None
        candidates.sort(
            key=lambda m: (
                m.price_per_sec,
                _QUALITY_ORDER.get(m.quality_tier, 0),
            ),
        )
        return candidates[0]

    def estimate_cost(
        self,
        *,
        model: VideoModel,
        duration_s: float,
    ) -> float:
        return round(
            model.price_per_sec * float(duration_s), 4,
        )

    # ── Spend tracking ───────────────────────────────────

    def spent_this_week(self, sku: str) -> float:
        if not sku:
            return 0.0
        cutoff = float(self._now_fn()) - 7 * 86400.0
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) "
                "FROM fal_spend "
                "WHERE sku=? AND created_at >= ?",
                (sku, cutoff),
            ).fetchone()
        return float(row[0] or 0.0)

    def _record_spend(
        self,
        *,
        sku: str,
        model_id: str,
        duration_s: float,
        cost_usd: float,
    ) -> None:
        now = float(self._now_fn())
        spend_id = uuid.uuid4().hex
        with self._lock:
            self._conn.execute(
                "INSERT INTO fal_spend("
                "spend_id, sku, model_id, duration_s, "
                "cost_usd, created_at) VALUES"
                "(?, ?, ?, ?, ?, ?)",
                (
                    spend_id, sku, model_id,
                    duration_s, cost_usd, now,
                ),
            )
            self._conn.commit()

    # ── Generate ────────────────────────────────────────

    def generate(
        self, request: VideoRequest,
    ) -> VideoResult:
        if not self.is_available():
            return VideoResult(
                ok=False,
                skipped_reason=(
                    f"{_ENV_KEY} not set"
                ),
            )
        model = self.pick_model(request)
        if model is None:
            return VideoResult(
                ok=False,
                skipped_reason=(
                    "no model meets quality + aspect + "
                    "duration"
                ),
            )
        cost = self.estimate_cost(
            model=model, duration_s=request.duration_s,
        )
        spent = self.spent_this_week(request.sku)
        if spent + cost > self._cap:
            return VideoResult(
                ok=False,
                skipped_reason=(
                    f"weekly cap ${self._cap:.2f} "
                    f"(${spent:.2f} spent) would be "
                    f"exceeded by ${cost:.2f}"
                ),
            )
        url = f"{self._base}/{model.model_id}"
        body = {
            "prompt": request.prompt,
            "aspect_ratio": request.aspect,
            "duration": request.duration_s,
            "sku": request.sku,
            "seed": request.seed or None,
        }
        if request.reference_image_url:
            body["image_url"] = (
                request.reference_image_url
            )
        try:
            resp = self._client().post(
                url,
                headers={
                    "Authorization": (
                        f"Key {self._api_key}"
                    ),
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=self._timeout,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "fal generate network: %s", exc,
            )
            return VideoResult(
                ok=False,
                model_id=model.model_id,
                error=f"network: {exc}",
            )
        status = int(
            getattr(resp, "status_code", 0),
        )
        if status >= 400:
            return VideoResult(
                ok=False,
                model_id=model.model_id,
                error=(
                    f"HTTP {status}: "
                    f"{(getattr(resp, 'text', '') or '')[:120]}"
                ),
            )
        try:
            payload = resp.json()
        except Exception as exc:  # noqa: BLE001
            return VideoResult(
                ok=False,
                model_id=model.model_id,
                error=f"bad JSON: {exc}",
            )
        video_url = str(
            (payload or {}).get("video", {}).get("url")
            or payload.get("video_url")
            or payload.get("url", ""),
        )
        request_id = str(
            payload.get("request_id", ""),
        )
        if not video_url:
            return VideoResult(
                ok=False,
                model_id=model.model_id,
                error="no video_url in response",
            )
        self._record_spend(
            sku=request.sku,
            model_id=model.model_id,
            duration_s=request.duration_s,
            cost_usd=cost,
        )
        return VideoResult(
            ok=True,
            model_id=model.model_id,
            video_url=video_url,
            cost_usd=cost,
            duration_s=request.duration_s,
            request_id=request_id,
        )

    # ── Diagnostics ─────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total = float(
                self._conn.execute(
                    "SELECT COALESCE(SUM(cost_usd), 0) "
                    "FROM fal_spend",
                ).fetchone()[0] or 0.0,
            )
            calls = int(
                self._conn.execute(
                    "SELECT COUNT(*) FROM fal_spend",
                ).fetchone()[0],
            )
        return {
            "adapter": "fal_video",
            "configured": bool(self._api_key),
            "weekly_cap_usd": self._cap,
            "total_spend_usd": round(total, 4),
            "total_generations": calls,
            "catalogue_size": len(self._catalogue),
        }

    def close(self) -> None:
        with self._lock:
            self._conn.close()
