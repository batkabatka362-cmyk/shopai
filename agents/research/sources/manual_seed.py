"""Manual seed source — owner-curated winners from a JSON file.

The simplest real ``WinnerSource``. Owners drop a JSON file
(default path: ``data/winner_seeds.json``) with an array of winner
dicts; the source reads + validates + yields candidates on every
fetch. Perfect for:

  * bootstrapping before real scrapers are configured
  * deterministic testing (ship a fixture file with known seeds)
  * owner override — pin specific products the owner wants to
    launch regardless of what scrapers say

Format (each entry is a winner):

    {
      "title": "Pet Slow-Feeder Bowl",
      "price": 29.99,
      "cost": 8.50,
      "daily_sales": 25,
      "saturation_score": 0.25,
      "image_url": "https://...",
      "url": "https://aliexpress.com/item/...",
      "tags": ["pet", "feeder"],
      "external_id": "ali-1005006...",
      "source": "aliexpress_manual"   // optional override
    }

Missing optional fields default to sensible zeros; ``title`` is the
only hard requirement. Invalid entries are skipped with a debug log.
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from pathlib import Path
from typing import Any, Iterable

from agents.research.winner_searcher import (
    ProductCandidate, WinnerSource,
)
from utils.logger import get_logger


logger = get_logger("agents.research.sources.manual_seed")


_DEFAULT_PATH = Path("data/winner_seeds.json")


class ManualSeedSource(WinnerSource):
    """File-backed winner source. Re-reads the file on each fetch
    so owners can hot-update the list without restarting."""

    name = "manual_seed"

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        default_source: str = "manual",
    ) -> None:
        self._path = Path(
            path if path is not None else _DEFAULT_PATH,
        )
        self._default_source = str(default_source)
        self._lock = threading.Lock()
        self._last_read_ok = False
        self._last_read_count = 0
        self._last_error = ""

    def is_available(self) -> bool:
        return self._path.exists()

    def fetch(
        self, *, limit: int = 100,
    ) -> list[ProductCandidate]:
        if not self._path.exists():
            with self._lock:
                self._last_read_ok = False
                self._last_read_count = 0
                self._last_error = (
                    f"seed file missing: {self._path}"
                )
            return []
        try:
            data = json.loads(self._path.read_text())
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "manual_seed parse failed: %s", exc,
            )
            with self._lock:
                self._last_read_ok = False
                self._last_read_count = 0
                self._last_error = (
                    f"parse failed: {exc}"
                )
            return []
        entries: list[dict[str, Any]]
        if isinstance(data, list):
            entries = data
        elif isinstance(data, dict) and isinstance(
            data.get("winners"), list,
        ):
            entries = data["winners"]
        else:
            with self._lock:
                self._last_read_ok = False
                self._last_read_count = 0
                self._last_error = (
                    "top-level must be a list or "
                    "{ 'winners': [...] }"
                )
            return []
        out: list[ProductCandidate] = []
        for raw in entries[: max(1, int(limit))]:
            if not isinstance(raw, dict):
                continue
            title = str(raw.get("title") or "").strip()
            if not title:
                logger.debug(
                    "manual_seed entry missing title: %s",
                    raw,
                )
                continue
            try:
                price = float(raw.get("price", 0.0) or 0.0)
                cost = float(raw.get("cost", 0.0) or 0.0)
                daily_sales = float(
                    raw.get("daily_sales", 0.0) or 0.0,
                )
                saturation = float(
                    raw.get("saturation_score", 0.0) or 0.0,
                )
            except (TypeError, ValueError) as exc:
                logger.debug(
                    "manual_seed entry type error: %s",
                    exc,
                )
                continue
            tags_raw = raw.get("tags") or []
            tags = (
                tuple(
                    str(t) for t in tags_raw if t
                )
                if isinstance(tags_raw, (list, tuple))
                else ()
            )
            ext_id = str(
                raw.get("external_id")
                or raw.get("id")
                or f"seed_{uuid.uuid4().hex[:10]}",
            )
            source = str(
                raw.get("source") or self._default_source,
            )
            out.append(ProductCandidate(
                source=source,
                external_id=ext_id,
                title=title,
                price=price,
                cost=cost,
                daily_sales=daily_sales,
                saturation_score=max(
                    0.0, min(1.0, saturation),
                ),
                image_url=str(
                    raw.get("image_url") or "",
                ),
                url=str(raw.get("url") or ""),
                tags=tags,
                raw=dict(raw),
            ))
        with self._lock:
            self._last_read_ok = True
            self._last_read_count = len(out)
            self._last_error = ""
        return out

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "path": str(self._path),
                "exists": self._path.exists(),
                "last_read_ok": self._last_read_ok,
                "last_read_count": self._last_read_count,
                "last_error": self._last_error,
            }


def write_seed_template(
    path: str | Path | None = None,
) -> Path:
    """Write a commented example seed file for owners to edit.

    Returns the path actually written (so callers can print it).
    """
    target = Path(
        path if path is not None else _DEFAULT_PATH,
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    template: dict[str, Any] = {
        "_comment": (
            "Paste winner dicts into `winners`. Missing "
            "numeric fields default to 0. Keep the list "
            "sorted — WinnerSearcher dedupes by title."
        ),
        "winners": [
            {
                "title": "Example Pet Slow-Feeder Bowl",
                "price": 29.99,
                "cost": 8.50,
                "daily_sales": 25,
                "saturation_score": 0.25,
                "image_url": "https://example.cdn/bowl.jpg",
                "url": "https://aliexpress.com/item/example",
                "tags": ["pet", "feeder", "anti-gulp"],
                "source": "aliexpress_manual",
            },
        ],
    }
    target.write_text(json.dumps(template, indent=2))
    return target
