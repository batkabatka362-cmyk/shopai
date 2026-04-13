"""AnalyticsAPI — fetches analytics data from Google Analytics 4 and Mixpanel.

Both platform methods return a normalised dict:
    {
        "platform":  str,
        "property":  str,
        "date_range": {"since": str, "until": str},
        "records":   list[dict],
        "errors":    list[str],
    }
"""
from __future__ import annotations

import logging
import time
from typing import Any

from utils.helpers import safe_float, safe_int
# Reuse the shared Retry-After parser from the Shopify client
# (pass 43). Audit pass 46.
from .shopify_api import _parse_retry_after

try:
    import requests as _requests
    _REQUESTS_AVAILABLE = True
except ImportError:  # pragma: no cover
    _requests = None  # type: ignore[assignment]
    _REQUESTS_AVAILABLE = False

logger = logging.getLogger("data_pipeline.analytics_api")


def _safe_post(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    max_retries: int = 3,
    retry_delay: float = 1.0,
) -> dict[str, Any]:
    """POST helper with retry that returns parsed JSON or an ``_error`` dict.

    Pre-audit the helper had NO retry — a single 429 / 5xx / network
    blip lost the entire report. Audit pass 46 adds parity with the
    ads_api / shopify_api retry path.
    """
    if not _REQUESTS_AVAILABLE:
        logger.warning("requests not installed; skipping HTTP call to %s", url)
        return {"_error": "requests library not installed"}

    last_exc: Exception | None = None
    for attempt in range(1, max(1, max_retries) + 1):
        try:
            resp = _requests.post(url, headers=headers, json=payload, timeout=30)
            if resp.status_code == 429:
                wait = _parse_retry_after(
                    resp.headers.get("Retry-After", ""),
                    retry_delay * attempt,
                )
                logger.warning("Rate-limited (%s); sleeping %.1fs", url, wait)
                time.sleep(wait)
                continue
            if 500 <= resp.status_code < 600:
                last_exc = Exception(f"HTTP {resp.status_code}")
                if attempt < max_retries:
                    time.sleep(retry_delay * attempt)
                    continue
                return {"_error": f"HTTP {resp.status_code}"}
            resp.raise_for_status()
            try:
                data = resp.json()
            except ValueError as exc:
                return {"_error": f"invalid JSON: {exc}"}
            return data if isinstance(data, dict) else {"_error": "non-dict response"}
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < max_retries:
                time.sleep(retry_delay * attempt)

    logger.error("POST %s failed after %d attempts: %s", url, max_retries, last_exc)
    return {"_error": f"failed after {max_retries} attempts: {last_exc}"}


def _safe_get(
    url: str,
    params: dict[str, Any],
    headers: dict[str, str] | None = None,
    max_retries: int = 3,
    retry_delay: float = 1.0,
) -> dict[str, Any]:
    """GET helper with retry that returns parsed JSON or an ``_error`` dict."""
    if not _REQUESTS_AVAILABLE:
        logger.warning("requests not installed; skipping HTTP call to %s", url)
        return {"_error": "requests library not installed"}

    last_exc: Exception | None = None
    for attempt in range(1, max(1, max_retries) + 1):
        try:
            resp = _requests.get(url, params=params, headers=headers or {}, timeout=30)
            if resp.status_code == 429:
                wait = _parse_retry_after(
                    resp.headers.get("Retry-After", ""),
                    retry_delay * attempt,
                )
                logger.warning("Rate-limited (%s); sleeping %.1fs", url, wait)
                time.sleep(wait)
                continue
            if 500 <= resp.status_code < 600:
                last_exc = Exception(f"HTTP {resp.status_code}")
                if attempt < max_retries:
                    time.sleep(retry_delay * attempt)
                    continue
                return {"_error": f"HTTP {resp.status_code}"}
            resp.raise_for_status()
            try:
                data = resp.json()
            except ValueError as exc:
                return {"_error": f"invalid JSON: {exc}"}
            return data if isinstance(data, dict) else {"_error": "non-dict response"}
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < max_retries:
                time.sleep(retry_delay * attempt)

    logger.error("GET %s failed after %d attempts: %s", url, max_retries, last_exc)
    return {"_error": f"failed after {max_retries} attempts: {last_exc}"}


class AnalyticsAPI:
    """Unified adapter for Google Analytics 4 and Mixpanel analytics platforms."""

    # ------------------------------------------------------------------
    # Google Analytics 4
    # ------------------------------------------------------------------

    _GA4_BASE = "https://analyticsdata.googleapis.com/v1beta"

    def fetch_google_analytics(
        self,
        property_id: str,
        credentials: dict[str, str],
        metrics: list[str] | None = None,
        date_range: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Fetch report data from Google Analytics 4 Data API.

        Args:
            property_id:  GA4 property ID, e.g. ``"123456789"``.
            credentials:  ``{"access_token": str}``.
            metrics:      GA4 metric names, e.g. ``["sessions", "bounceRate"]``.
                          Defaults to a standard set if omitted.
            date_range:   ``{"since": "YYYY-MM-DD", "until": "YYYY-MM-DD"}``.
                          Defaults to last 30 days.

        Returns:
            Normalised dict with ``platform``, ``property``, ``records``, ``errors``.
        """
        # Defensive coercion of public entry point. Audit pass 46.
        property_id = property_id if isinstance(property_id, str) else ""
        credentials = credentials if isinstance(credentials, dict) else {}
        date_range = _ensure_date_range(date_range, 30)
        if not isinstance(metrics, list) or not metrics:
            metrics = [
                "sessions",
                "totalUsers",
                "newUsers",
                "bounceRate",
                "averageSessionDuration",
                "screenPageViews",
                "conversions",
                "totalRevenue",
            ]
        metrics = [m for m in metrics if isinstance(m, str) and m]

        url = f"{self._GA4_BASE}/properties/{property_id}:runReport"
        headers = {
            "Authorization": f"Bearer {credentials.get('access_token') or ''}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "dateRanges": [
                {"startDate": date_range["since"], "endDate": date_range["until"]}
            ],
            "metrics": [{"name": m} for m in metrics],
            "dimensions": [{"name": "date"}, {"name": "pagePath"}],
        }

        raw = _safe_post(url, headers, payload)
        records: list[dict[str, Any]] = []
        errors: list[str] = []

        if "_error" in raw:
            errors.append(raw["_error"])
        else:
            # Pre-audit ``.get("dimensionHeaders", [])`` returned
            # ``[]`` only when the key was MISSING. A present-
            # but-None "dimensionHeaders" crashed the list
            # comprehension. Same ``or []`` / ``or {}`` pattern
            # as passes 32/36/40/41/42/43/45.
            dim_headers_raw = raw.get("dimensionHeaders") or []
            metric_headers_raw = raw.get("metricHeaders") or []
            dimension_headers = [
                h.get("name") for h in dim_headers_raw if isinstance(h, dict)
            ]
            metric_headers = [
                h.get("name") for h in metric_headers_raw if isinstance(h, dict)
            ]

            rows = raw.get("rows") or []
            if not isinstance(rows, list):
                rows = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                try:
                    record: dict[str, Any] = {}
                    dim_values = row.get("dimensionValues") or []
                    if isinstance(dim_values, list):
                        for i, val in enumerate(dim_values):
                            if not isinstance(val, dict):
                                continue
                            key = dimension_headers[i] if i < len(dimension_headers) else f"dim_{i}"
                            record[key] = val.get("value") or ""
                    metric_values = row.get("metricValues") or []
                    if isinstance(metric_values, list):
                        for i, val in enumerate(metric_values):
                            if not isinstance(val, dict):
                                continue
                            key = metric_headers[i] if i < len(metric_headers) else f"metric_{i}"
                            raw_val = val.get("value")
                            if raw_val is None:
                                record[key] = 0.0
                            else:
                                # safe_float handles strings,
                                # ints, "", "N/A", and None.
                                coerced = safe_float(raw_val, default=float("nan"))
                                import math
                                if math.isnan(coerced):
                                    # Preserve the raw string
                                    # for non-numeric dimensions
                                    # that GA4 sometimes emits.
                                    record[key] = raw_val
                                else:
                                    record[key] = coerced
                    records.append(record)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"Row parse error: {exc}")

        logger.info(
            "GA4 property %s: fetched %d rows (%s to %s)",
            property_id,
            len(records),
            date_range["since"],
            date_range["until"],
        )
        return {
            "platform": "google_analytics",
            "property": property_id,
            "date_range": date_range,
            "records": records,
            "errors": errors,
        }

    # ------------------------------------------------------------------
    # Mixpanel
    # ------------------------------------------------------------------

    _MIXPANEL_BASE = "https://data.mixpanel.com/api/2.0"

    def fetch_mixpanel(
        self,
        project_id: str,
        api_secret: str,
        event_names: list[str] | None = None,
        date_range: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Fetch event counts from the Mixpanel Export / Engage API.

        Uses the JQL ``/export`` endpoint aggregated via the ``/events`` endpoint.

        Args:
            project_id:  Mixpanel project ID (used for scoping, sent as header).
            api_secret:  Project secret (used in HTTP Basic auth).
            event_names: List of event names to retrieve.  ``None`` → all events.
            date_range:  ``{"since": "YYYY-MM-DD", "until": "YYYY-MM-DD"}``.

        Returns:
            Normalised dict with ``platform``, ``project``, ``records``, ``errors``.
        """
        import base64

        project_id = project_id if isinstance(project_id, str) else ""
        api_secret = api_secret if isinstance(api_secret, str) else ""
        date_range = _ensure_date_range(date_range, 30)

        # Mixpanel Events endpoint uses ``from_date`` / ``to_date``
        url = f"{self._MIXPANEL_BASE}/events"
        token = base64.b64encode(f"{api_secret}:".encode()).decode()
        headers = {
            "Authorization": f"Basic {token}",
            "Accept": "application/json",
        }
        params: dict[str, Any] = {
            "project_id": project_id,
            "from_date": date_range["since"],
            "to_date": date_range["until"],
            "unit": "day",
            "interval": 1,
            "type": "general",
        }
        if isinstance(event_names, list) and event_names:
            params["event"] = [n for n in event_names if isinstance(n, str)]

        raw = _safe_get(url, params, headers)
        records: list[dict[str, Any]] = []
        errors: list[str] = []

        if "_error" in raw:
            errors.append(raw["_error"])
        else:
            # Mixpanel returns {"data": {"series": [...], "values": {event: {date: count}}}}
            data_block = raw.get("data") or {}
            if not isinstance(data_block, dict):
                data_block = {}
            series = data_block.get("series") or []
            values = data_block.get("values") or {}
            if not isinstance(series, list):
                series = []
            if not isinstance(values, dict):
                values = {}

            for event_name, date_counts in values.items():
                if not isinstance(date_counts, dict):
                    continue
                for date_str in series:
                    if not isinstance(date_str, str):
                        continue
                    records.append(
                        {
                            "event": event_name,
                            "date": date_str,
                            "count": safe_int(date_counts.get(date_str)),
                        }
                    )

        logger.info(
            "Mixpanel project %s: fetched %d event-day rows",
            project_id,
            len(records),
        )
        return {
            "platform": "mixpanel",
            "project": project_id,
            "date_range": date_range,
            "records": records,
            "errors": errors,
        }


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _default_date_range(days: int) -> dict[str, str]:
    """Return ``{"since": ..., "until": ...}`` covering the last *days* days."""
    import datetime

    if not isinstance(days, int) or days <= 0:
        days = 30
    today = datetime.date.today()
    since = today - datetime.timedelta(days=days)
    return {"since": since.isoformat(), "until": today.isoformat()}


def _ensure_date_range(date_range: Any, default_days: int) -> dict[str, str]:
    """Coerce a caller-supplied date_range to a well-formed dict.

    Mirrors ``AdsAPI._ensure_date_range`` — pre-audit both
    files did ``date_range or default`` then read
    ``date_range["since"]`` which crashed on a non-dict input
    or a missing key. Audit pass 46.
    """
    if not isinstance(date_range, dict):
        return _default_date_range(default_days)
    since = date_range.get("since")
    until = date_range.get("until")
    if not isinstance(since, str) or not isinstance(until, str):
        return _default_date_range(default_days)
    return {"since": since, "until": until}
