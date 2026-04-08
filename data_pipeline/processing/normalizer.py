"""DataNormalizer — normalizes values, scales, and formats across data records."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse, urlunparse

from utils.helpers import safe_float

logger = logging.getLogger("data_pipeline.normalizer")

# Ordered list of date formats tried during normalize_date
_DATE_FORMATS = [
    "%Y-%m-%d",                # ISO 8601 date
    "%Y-%m-%dT%H:%M:%S",       # ISO 8601 datetime (no tz)
    "%Y-%m-%dT%H:%M:%SZ",      # ISO 8601 datetime (UTC Z)
    "%Y-%m-%dT%H:%M:%S%z",     # ISO 8601 with offset
    "%d/%m/%Y",                # DD/MM/YYYY
    "%m/%d/%Y",                # MM/DD/YYYY
    "%d-%m-%Y",                # DD-MM-YYYY
    "%m-%d-%Y",                # MM-DD-YYYY
    "%B %d, %Y",               # "January 01, 2024"
    "%b %d, %Y",               # "Jan 01, 2024"
    "%d %B %Y",                # "01 January 2024"
    "%d %b %Y",                # "01 Jan 2024"
    "%Y%m%d",                  # YYYYMMDD compact
]


class DataNormalizer:
    """Normalizes data records to consistent formats, scales, and types.

    The primary entry point is :meth:`normalize`, which applies a
    ``config`` dict to each record.  All scalar helper methods are also
    available for direct use.
    """

    # ------------------------------------------------------------------
    # Primary entry point
    # ------------------------------------------------------------------

    def normalize(
        self,
        data: list[dict[str, Any]],
        config: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Apply normalization rules defined in *config* to every record.

        Config format::

            {
                "price_fields":  ["price", "sale_price"],  # → normalize_price
                "date_fields":   ["created_at", "updated_at"],  # → normalize_date
                "url_fields":    ["product_url", "image_url"],   # → normalize_url
                "min_max_fields": {
                    "views":   {"min": 0, "max": 10000},
                },
                "z_score_fields": {
                    "revenue": {"mean": 500.0, "std": 200.0},
                },
                "rename": {"old_name": "new_name"},
            }

        Fields not mentioned in *config* are passed through unchanged.

        Args:
            data:   Input records.
            config: Normalization config; ``None`` means pass-through.

        Returns:
            New list of normalized records.
        """
        # Defensive coercion of public entry point. Audit pass 41.
        if not isinstance(data, list):
            return []
        data = [r for r in data if isinstance(r, dict)]

        if not config or not isinstance(config, dict):
            return [dict(r) for r in data]

        logger.info("Normalizing %d records", len(data))
        price_fields: list[str] = config.get("price_fields") or []
        date_fields: list[str] = config.get("date_fields") or []
        url_fields: list[str] = config.get("url_fields") or []
        min_max_fields: dict[str, dict[str, float]] = config.get("min_max_fields") or {}
        z_score_fields: dict[str, dict[str, float]] = config.get("z_score_fields") or {}
        rename: dict[str, str] = config.get("rename") or {}

        # Normalise config shapes so downstream ``in`` /
        # ``.get`` / ``["key"]`` operations can't crash on
        # non-list / non-dict values.
        if not isinstance(price_fields, list):
            price_fields = []
        if not isinstance(date_fields, list):
            date_fields = []
        if not isinstance(url_fields, list):
            url_fields = []
        if not isinstance(min_max_fields, dict):
            min_max_fields = {}
        if not isinstance(z_score_fields, dict):
            z_score_fields = {}
        if not isinstance(rename, dict):
            rename = {}

        result: list[dict[str, Any]] = []
        for record in data:
            new_rec: dict[str, Any] = {}
            for key, value in record.items():
                # Apply renames
                out_key = rename.get(key, key)

                if key in price_fields and value is not None:
                    new_rec[out_key] = self.normalize_price(str(value))
                elif key in date_fields and value is not None:
                    new_rec[out_key] = self.normalize_date(str(value))
                elif key in url_fields and value is not None:
                    new_rec[out_key] = self.normalize_url(str(value))
                elif key in min_max_fields and value is not None:
                    cfg = min_max_fields.get(key)
                    if not isinstance(cfg, dict):
                        new_rec[out_key] = value
                        continue
                    lo = safe_float(cfg.get("min"))
                    hi = safe_float(cfg.get("max"))
                    # ``float(value)`` crashes on non-numeric
                    # strings; safe_float handles "$99.99",
                    # None, and garbage. Audit pass 41.
                    new_rec[out_key] = self.min_max_scale(
                        safe_float(value), lo, hi
                    )
                elif key in z_score_fields and value is not None:
                    cfg = z_score_fields.get(key)
                    if not isinstance(cfg, dict):
                        new_rec[out_key] = value
                        continue
                    mean = safe_float(cfg.get("mean"))
                    std = safe_float(cfg.get("std"))
                    new_rec[out_key] = self.z_score(
                        safe_float(value), mean, std
                    )
                else:
                    new_rec[out_key] = value

            result.append(new_rec)

        return result

    # ------------------------------------------------------------------
    # Scalar helpers
    # ------------------------------------------------------------------

    @staticmethod
    def min_max_scale(value: float, min_val: float, max_val: float) -> float:
        """Scale *value* to ``[0, 1]`` using min-max normalization.

        Returns ``0.0`` when ``min_val == max_val`` to avoid division by zero.

        Args:
            value:   The raw numeric value.
            min_val: Minimum of the range.
            max_val: Maximum of the range.

        Returns:
            Scaled value in ``[0.0, 1.0]``.
        """
        if max_val == min_val:
            return 0.0
        return (value - min_val) / (max_val - min_val)

    @staticmethod
    def z_score(value: float, mean: float, std: float) -> float:
        """Return the Z-score of *value* given *mean* and *std*.

        Returns ``0.0`` when ``std == 0`` to avoid division by zero.

        Args:
            value: Raw numeric value.
            mean:  Distribution mean.
            std:   Distribution standard deviation.

        Returns:
            Z-score as a float.
        """
        if std == 0.0:
            return 0.0
        return (value - mean) / std

    @staticmethod
    def normalize_price(price_str: str) -> float:
        """Convert a price string to a float.

        Handles formats like:
        * ``"$1,234.56"`` → ``1234.56``
        * ``"£99.99"``    → ``99.99``
        * ``"1.234,56"``  → ``1234.56``  (European format)
        * ``"FREE"``      → ``0.0``

        Args:
            price_str: Raw price string.

        Returns:
            Numeric price as float; ``0.0`` if parsing fails.
        """
        if not price_str:
            return 0.0
        s = price_str.strip().upper()
        if s in ("FREE", "N/A", "-", ""):
            return 0.0

        # Remove all currency symbols and whitespace
        s = re.sub(r"[^\d.,\-]", "", s)

        # Detect European format: "1.234,56" (dot as thousands, comma as decimal)
        if re.search(r"\d\.\d{3},\d{2}$", s):
            s = s.replace(".", "").replace(",", ".")
        else:
            # Standard: remove thousands commas, keep decimal point
            s = s.replace(",", "")

        try:
            return float(s)
        except ValueError:
            logger.warning("normalize_price: cannot parse '%s'", price_str)
            return 0.0

    @staticmethod
    def normalize_date(date_str: str) -> str:
        """Parse *date_str* in various formats and return ISO 8601 (``YYYY-MM-DD``).

        Args:
            date_str: Raw date/datetime string.

        Returns:
            ISO 8601 date string, or the original string if parsing fails.
        """
        if not date_str:
            return date_str
        s = date_str.strip()
        for fmt in _DATE_FORMATS:
            try:
                dt = datetime.strptime(s, fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue
        # Try ISO-8601 with fractional seconds
        try:
            s_clean = re.sub(r"\.\d+", "", s)
            dt = datetime.fromisoformat(s_clean.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            pass
        logger.warning("normalize_date: cannot parse '%s'", date_str)
        return date_str

    @staticmethod
    def normalize_url(url: str) -> str:
        """Normalise a URL: lowercase scheme+host, remove default ports and fragments.

        Args:
            url: Raw URL string.

        Returns:
            Normalised URL string, or the original string on parse failure.
        """
        if not url or not url.strip():
            return url
        url = url.strip()
        try:
            p = urlparse(url)
            scheme = p.scheme.lower() or "https"
            netloc = p.netloc.lower()

            # Remove default ports
            if ":" in netloc:
                host, port_str = netloc.rsplit(":", 1)
                if (scheme == "http" and port_str == "80") or (
                    scheme == "https" and port_str == "443"
                ):
                    netloc = host

            # Rebuild without fragment
            normalised = urlunparse(
                (scheme, netloc, p.path, p.params, p.query, "")
            )
            return normalised
        except Exception:  # noqa: BLE001
            return url
