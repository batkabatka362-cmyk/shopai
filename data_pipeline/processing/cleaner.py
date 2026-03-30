"""DataCleaner — removes noise, fixes formats, and handles missing values."""
from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any

logger = logging.getLogger("data_pipeline.cleaner")


class DataCleaner:
    """Cleans raw data records in place or returns new lists.

    All public methods are safe to chain and never mutate the input list
    — they return new lists of new dicts.
    """

    # ------------------------------------------------------------------
    # Primary entry point
    # ------------------------------------------------------------------

    def clean(self, data: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Run the full cleaning pipeline on *data*.

        Steps (in order):
        1. Strip leading/trailing whitespace from every string value.
        2. Remove records where *all* values are ``None`` or empty string.
        3. Normalise text: unicode NFKC, collapse whitespace, lower-case
           only for known text fields (``name``, ``title``, ``description``).

        Args:
            data: Raw list of record dicts.

        Returns:
            Cleaned list; records that are completely empty are dropped.
        """
        logger.info("Cleaning %d records", len(data))
        result = self.strip_whitespace(data)
        result = self.remove_nulls(result)
        result = [
            {k: (self.normalize_text(v) if k in ("name", "title", "description") and isinstance(v, str) else v)
             for k, v in record.items()}
            for record in result
        ]
        logger.info("Cleaning complete: %d records remain", len(result))
        return result

    # ------------------------------------------------------------------
    # Individual operations (all return new lists/values)
    # ------------------------------------------------------------------

    def remove_duplicates(
        self,
        data: list[dict[str, Any]],
        key_field: str,
    ) -> list[dict[str, Any]]:
        """Return *data* with duplicate records removed, keeping the first occurrence.

        Args:
            data:      Input records.
            key_field: The field whose value is used as the uniqueness key.
                       Records missing this field are always kept.

        Returns:
            Deduplicated list in original order.
        """
        seen: set[Any] = set()
        result: list[dict[str, Any]] = []
        for record in data:
            key = record.get(key_field)
            if key is None or key not in seen:
                result.append(dict(record))
                if key is not None:
                    seen.add(key)
        removed = len(data) - len(result)
        if removed:
            logger.debug("remove_duplicates: removed %d duplicates on '%s'", removed, key_field)
        return result

    def fill_missing(
        self,
        data: list[dict[str, Any]],
        field: str,
        default_value: Any,
    ) -> list[dict[str, Any]]:
        """Fill missing or ``None`` values in *field* with *default_value*.

        Args:
            data:          Input records.
            field:         The field name to fill.
            default_value: Value to use when the field is absent or ``None``.

        Returns:
            New list with filled records.
        """
        result: list[dict[str, Any]] = []
        filled = 0
        for record in data:
            new_record = dict(record)
            if new_record.get(field) is None:
                new_record[field] = default_value
                filled += 1
            result.append(new_record)
        logger.debug("fill_missing: filled %d records for field '%s'", filled, field)
        return result

    @staticmethod
    def strip_whitespace(data: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Strip leading/trailing whitespace from all string values in every record.

        Returns:
            New list with whitespace-stripped string values.
        """
        return [
            {k: v.strip() if isinstance(v, str) else v for k, v in record.items()}
            for record in data
        ]

    @staticmethod
    def remove_nulls(data: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Remove records that are empty (all values ``None`` or empty string).

        Note: this does *not* drop individual ``None`` fields — use
        :meth:`fill_missing` for that.  It drops entire records that carry
        no usable data.

        Returns:
            Filtered list.
        """
        result: list[dict[str, Any]] = []
        for record in data:
            if any(v is not None and v != "" for v in record.values()):
                result.append(record)
        return result

    @staticmethod
    def normalize_text(text: str) -> str:
        """Normalise a text string for consistent storage.

        Operations applied:
        * Unicode NFKC normalisation (e.g. ``ﬁ`` → ``fi``).
        * Strip leading / trailing whitespace.
        * Collapse internal runs of whitespace to a single space.
        * Remove non-printable / control characters (except ``\\n``).

        Args:
            text: Raw text string.

        Returns:
            Cleaned text string (preserves original case).
        """
        if not isinstance(text, str):
            return text  # type: ignore[return-value]
        text = unicodedata.normalize("NFKC", text)
        # Remove control characters (but keep newlines for multi-paragraph text)
        text = "".join(ch for ch in text if ch == "\n" or not unicodedata.category(ch).startswith("C"))
        text = re.sub(r"[ \t]+", " ", text)  # collapse horizontal whitespace
        return text.strip()
