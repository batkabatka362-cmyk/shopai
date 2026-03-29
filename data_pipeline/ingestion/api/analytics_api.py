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
from typing import Any

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
) -> dict[str, Any]:
    """POST helper that returns parsed JSON or an empty dict on any error."""
    if not _REQUESTS_AVAILABLE:
        logger.warning("requests not installed; skipping HTTP call to %s", url)
        return {}
    try:
        resp = _requests.post(url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:  # noqa: BLE001
        logger.error("POST %s failed: %s", url, exc)
        return {"_error": str(exc)}


def _safe_get(
    url: str,
    params: dict[str, Any],
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """GET helper that returns parsed JSON or an empty dict on any error."""
    if not _REQUESTS_AVAILABLE:
        logger.warning("requests not installed; skipping HTTP call to %s", url)
        return {}
    try:
        resp = _requests.get(url, params=params, headers=headers or {}, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:  # noqa: BLE001
        logger.error("GET %s failed: %s", url, exc)
        return {"_error": str(exc)}


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
        date_range = date_range or _default_date_range(30)
        metrics = metrics or [
            "sessions",
            "totalUsers",
            "newUsers",
            "bounceRate",
            "averageSessionDuration",
            "screenPageViews",
            "conversions",
            "totalRevenue",
        ]

        url = f"{self._GA4_BASE}/properties/{property_id}:runReport"
        headers = {
            "Authorization": f"Bearer {credentials.get('access_token', '')}",
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
            dimension_headers = [h.get("name") for h in raw.get("dimensionHeaders", [])]
            metric_headers = [h.get("name") for h in raw.get("metricHeaders", [])]

            for row in raw.get("rows", []):
                try:
                    record: dict[str, Any] = {}
                    for i, val in enumerate(row.get("dimensionValues", [])):
                        key = dimension_headers[i] if i < len(dimension_headers) else f"dim_{i}"
                        record[key] = val.get("value", "")
                    for i, val in enumerate(row.get("metricValues", [])):
                        key = metric_headers[i] if i < len(metric_headers) else f"metric_{i}"
                        raw_val = val.get("value", "0")
                        try:
                            record[key] = float(raw_val)
                        except ValueError:
                            record[key] = raw_val
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

        date_range = date_range or _default_date_range(30)

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
        if event_names:
            params["event"] = event_names  # Mixpanel accepts repeated keys via list

        raw = _safe_get(url, params, headers)
        records: list[dict[str, Any]] = []
        errors: list[str] = []

        if "_error" in raw:
            errors.append(raw["_error"])
        else:
            # Mixpanel returns {"data": {"series": [...], "values": {event: {date: count}}}}
            data_block = raw.get("data", {})
            series = data_block.get("series", [])
            values = data_block.get("values", {})

            for event_name, date_counts in values.items():
                for date_str in series:
                    count = date_counts.get(date_str, 0)
                    records.append(
                        {
                            "event": event_name,
                            "date": date_str,
                            "count": int(count),
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
# Module-level helper
# ---------------------------------------------------------------------------


def _default_date_range(days: int) -> dict[str, str]:
    """Return ``{"since": ..., "until": ...}`` covering the last *days* days."""
    import datetime

    today = datetime.date.today()
    since = today - datetime.timedelta(days=days)
    return {"since": since.isoformat(), "until": today.isoformat()}
