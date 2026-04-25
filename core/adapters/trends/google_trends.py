"""Google Trends — free trending-searches signal (L2 perception).

Sprint 3 S3-3 in docs/AGI_STACK.md. Google Trends exposes a public
``/trends/api/dailytrends`` endpoint that returns top trending
searches by geo with no API key and no auth. This adapter wraps it
with SQLite caching (6h TTL by default) so the brain can consume
trend keywords without pounding Google.

Why this matters: until now the winner pool was limited to supplier-
catalogue breadth (CJ / AliExpress / manual seed / peer store). The
public trends feed turns "what are people searching right now in the
US and EU?" into cheap, refreshable signal the niche_discoverer can
mix into its rollup.

Failure handling: network / parse errors are caught, stats() surfaces
``last_error``, and ``top_searches()`` returns ``[]`` so callers
downstream can degrade gracefully. No dependency on pytrends — the
endpoint speaks JSON directly (prefixed with ``)]}',`` which is
stripped before decode).

Markets: US + EU focus per owner target. For EU we aggregate GB + DE
+ FR as proxies since Google Trends has no single "EU" geo.

Pure stdlib + requests (existing dep). Thread-safe (Lock). LLM-free.
Deterministic given a fixed http client.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from utils.logger import get_logger


logger = get_logger("core.adapters.trends.google_trends")


_ENDPOINT = "https://trends.google.com/trends/api/dailytrends"
_DEFAULT_TIMEOUT = 10.0
_DEFAULT_CACHE_TTL_S = 6 * 3600.0
_EU_PROXY_GEOS = ("GB", "DE", "FR", "IT", "ES")
_VALID_GEOS = ("US", "GB", "DE", "FR", "IT", "ES", "EU")

_JSON_PREFIX = ")]}',"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS trend_cache (
    geo         TEXT PRIMARY KEY,
    fetched_at  REAL NOT NULL,
    payload     TEXT NOT NULL
);
"""


@dataclass
class TrendingSearch:
    keyword: str
    geo: str
    traffic: str = ""
    related_queries: tuple[str, ...] = ()
    fetched_at: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "keyword": self.keyword,
            "geo": self.geo,
            "traffic": self.traffic,
            "related_queries": list(self.related_queries),
            "fetched_at": self.fetched_at,
        }


class GoogleTrendsAdapter:
    """Public Google Trends daily-trending-searches reader."""

    name = "google_trends"

    def __init__(
        self,
        *,
        db_path: str | Path = "data/google_trends.db",
        cache_ttl_s: float = _DEFAULT_CACHE_TTL_S,
        http: Any = None,
        timeout: float = _DEFAULT_TIMEOUT,
        now_fn: Any = None,
    ) -> None:
        if cache_ttl_s < 0:
            raise ValueError("cache_ttl_s must be ≥ 0")
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._ttl = float(cache_ttl_s)
        self._http = http
        self._timeout = float(timeout)
        self._now_fn = now_fn or time.time
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(
            str(self._path), check_same_thread=False,
        )
        self._last_error = ""
        self._last_fetch_count = 0
        with self._lock:
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def is_available(self) -> bool:
        return True

    # ── Public API ───────────────────────────────────────

    def top_searches(
        self,
        *,
        geo: str = "US",
        limit: int = 20,
        use_cache: bool = True,
    ) -> list[TrendingSearch]:
        """Return top trending search terms for a geography.

        ``geo='EU'`` aggregates GB + DE + FR + IT + ES as Google
        Trends has no single EU geo. For any other valid geo returns
        just that geo.
        """
        geo = str(geo).upper()
        if geo not in _VALID_GEOS:
            with self._lock:
                self._last_error = (
                    f"unsupported geo {geo!r}; "
                    f"allowed {_VALID_GEOS}"
                )
            return []
        if geo == "EU":
            merged: list[TrendingSearch] = []
            seen: set[str] = set()
            for sub in _EU_PROXY_GEOS:
                for t in self._top_searches_single(
                    geo=sub,
                    limit=limit,
                    use_cache=use_cache,
                ):
                    key = t.keyword.lower().strip()
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    merged.append(t)
                if len(merged) >= limit:
                    break
            return merged[:limit]
        return self._top_searches_single(
            geo=geo, limit=limit, use_cache=use_cache,
        )

    def _top_searches_single(
        self,
        *,
        geo: str,
        limit: int,
        use_cache: bool,
    ) -> list[TrendingSearch]:
        if use_cache:
            cached = self._cache_read(geo)
            if cached is not None:
                return self._parse_payload(
                    cached, geo, limit,
                )
        try:
            payload = self._fetch_payload(geo)
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._last_error = (
                    f"fetch {geo} failed: {exc}"
                )
            logger.debug(
                "google trends fetch %s failed: %s",
                geo, exc,
            )
            return []
        self._cache_write(geo, payload)
        parsed = self._parse_payload(payload, geo, limit)
        with self._lock:
            self._last_fetch_count = len(parsed)
            if parsed:
                self._last_error = ""
            elif not self._last_error:
                # Only overwrite if parsing didn't already set
                # a more specific error (json decode, etc.).
                self._last_error = "no trends parsed"
        return parsed

    # ── HTTP ─────────────────────────────────────────────

    def _fetch_payload(self, geo: str) -> str:
        client = self._http
        if client is None:
            import requests
            client = requests
        resp = client.get(
            _ENDPOINT,
            params={"geo": geo, "hl": "en-US"},
            timeout=self._timeout,
            headers={"Accept": "application/json"},
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"HTTP {resp.status_code}")
        return resp.text or ""

    # ── Parse ────────────────────────────────────────────

    def _parse_payload(
        self, raw: str, geo: str, limit: int,
    ) -> list[TrendingSearch]:
        body = (raw or "").lstrip()
        if body.startswith(_JSON_PREFIX):
            body = body[len(_JSON_PREFIX):]
        body = body.strip()
        if not body:
            return []
        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            with self._lock:
                self._last_error = f"json decode: {exc}"
            return []
        days = (
            (data or {})
            .get("default", {})
            .get("trendingSearchesDays", [])
        ) or []
        now = float(self._now_fn())
        out: list[TrendingSearch] = []
        for day in days:
            for item in day.get("trendingSearches", []) or []:
                keyword = (
                    item.get("title", {}).get("query", "")
                    if isinstance(item.get("title"), dict)
                    else ""
                ).strip()
                if not keyword:
                    continue
                traffic = str(
                    item.get("formattedTraffic", ""),
                )
                related = tuple(
                    str(r.get("query", ""))
                    for r in (
                        item.get("relatedQueries", []) or []
                    )
                    if isinstance(r, dict)
                    and r.get("query")
                )
                out.append(TrendingSearch(
                    keyword=keyword,
                    geo=geo,
                    traffic=traffic,
                    related_queries=related,
                    fetched_at=now,
                ))
                if len(out) >= limit:
                    return out
        return out

    # ── Cache ────────────────────────────────────────────

    def _cache_read(self, geo: str) -> str | None:
        now = float(self._now_fn())
        with self._lock:
            row = self._conn.execute(
                "SELECT fetched_at, payload FROM trend_cache "
                "WHERE geo=?",
                (geo,),
            ).fetchone()
        if row is None:
            return None
        age = now - float(row[0])
        if self._ttl > 0 and age > self._ttl:
            return None
        return str(row[1])

    def _cache_write(self, geo: str, payload: str) -> None:
        now = float(self._now_fn())
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO trend_cache"
                "(geo, fetched_at, payload) VALUES(?, ?, ?)",
                (geo, now, payload),
            )
            self._conn.commit()

    # ── Status ───────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT geo, fetched_at FROM trend_cache",
            ).fetchall()
            last_err = self._last_error
            last_count = self._last_fetch_count
        cache_entries = [
            {"geo": r[0], "age_s": float(self._now_fn()) - r[1]}
            for r in rows
        ]
        return {
            "adapter": self.name,
            "cache_entries": cache_entries,
            "cache_ttl_s": self._ttl,
            "last_error": last_err,
            "last_fetch_count": last_count,
        }

    def close(self) -> None:
        with self._lock:
            self._conn.close()
