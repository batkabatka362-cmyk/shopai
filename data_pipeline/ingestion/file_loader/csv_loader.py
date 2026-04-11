"""CSVLoader — loads CSV files into lists of dicts with optional schema validation.

Uses only the Python standard library (``csv`` module).
"""
from __future__ import annotations

import csv
import io
import logging
import os
from typing import Any

from utils.helpers import safe_float, safe_int

logger = logging.getLogger("data_pipeline.csv_loader")

# UTF-8 Byte-Order-Mark. Excel / Google Sheets often export
# CSVs with this prefix on the first cell, which silently
# corrupts the first column header. Audit pass 45.
_BOM = "\ufeff"


class CSVLoaderError(Exception):
    """Raised for unrecoverable CSV loading errors."""


class CSVLoader:
    """Loads CSV files into ``list[dict]`` with optional column validation.

    Args:
        delimiter: Field delimiter character (default ``,``).
        encoding:  File encoding (default ``utf-8``).
    """

    def __init__(self, delimiter: str = ",", encoding: str = "utf-8") -> None:
        self._delimiter = delimiter if isinstance(delimiter, str) and delimiter else ","
        self._encoding = encoding if isinstance(encoding, str) and encoding else "utf-8"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self, filepath: str) -> list[dict[str, Any]]:
        """Load *filepath* and return all rows as a list of dicts.

        The first row is treated as the header.

        Args:
            filepath: Absolute or relative path to a CSV file.

        Returns:
            List of row dicts; empty list if the file is empty or missing.

        Raises:
            CSVLoaderError: If the file cannot be opened or the path is
                invalid.
        """
        if not isinstance(filepath, str) or not filepath:
            raise CSVLoaderError("filepath must be a non-empty string")
        filepath = os.path.expanduser(filepath)
        if not os.path.isfile(filepath):
            raise CSVLoaderError(f"File not found: {filepath}")

        try:
            # ``encoding="utf-8-sig"`` automatically strips the
            # UTF-8 BOM when present, so ``csv.DictReader``
            # doesn't see ``\ufeff`` glued to the first column
            # name. Pre-audit ``self._encoding`` (usually
            # ``"utf-8"``) left the BOM in the header, silently
            # corrupting the first column name on every Excel
            # export. Audit pass 45.
            open_encoding = "utf-8-sig" if self._encoding.lower() == "utf-8" else self._encoding
            with open(filepath, newline="", encoding=open_encoding) as fh:
                reader = csv.DictReader(fh, delimiter=self._delimiter)
                rows = [self._cast_row(dict(row)) for row in reader]
        except OSError as exc:
            raise CSVLoaderError(f"Cannot open {filepath}: {exc}") from exc

        logger.info("Loaded %d rows from %s", len(rows), filepath)
        return rows

    def load_with_schema(
        self,
        filepath: str,
        schema: dict[str, type],
    ) -> list[dict[str, Any]]:
        """Load *filepath* and cast each column according to *schema*.

        Args:
            filepath: Path to the CSV file.
            schema:   Mapping of ``column_name → Python type``, e.g.
                      ``{"price": float, "quantity": int, "name": str}``.
                      Columns absent from the schema are kept as strings.
                      Rows that fail casting are skipped and logged.

        Returns:
            List of successfully cast row dicts.
        """
        rows = self.load(filepath)
        if not isinstance(schema, dict):
            return rows
        result: list[dict[str, Any]] = []
        skipped = 0

        for i, row in enumerate(rows, start=2):  # start=2: row 1 is the header
            try:
                cast_row = self._apply_schema(row, schema)
                result.append(cast_row)
            except (ValueError, TypeError) as exc:
                logger.warning("Row %d skipped due to cast error: %s", i, exc)
                skipped += 1

        if skipped:
            logger.info("load_with_schema: %d rows skipped (cast errors)", skipped)
        return result

    def validate_columns(
        self,
        rows: list[dict[str, Any]],
        required_columns: list[str],
    ) -> list[str]:
        """Check that every column in *required_columns* is present in *rows*.

        Args:
            rows:             The loaded data (as returned by :meth:`load`).
            required_columns: Column names that must exist.

        Returns:
            List of missing column names (empty list if all present).
        """
        if not isinstance(required_columns, list):
            return []
        if not rows:
            return list(required_columns)
        first = rows[0] if isinstance(rows[0], dict) else {}
        present = set(first.keys())
        missing = [col for col in required_columns if col not in present]
        if missing:
            logger.warning("Missing columns: %s", missing)
        return missing

    # ------------------------------------------------------------------
    # Convenience: load from a string
    # ------------------------------------------------------------------

    def load_string(self, csv_text: str) -> list[dict[str, Any]]:
        """Parse *csv_text* as CSV content and return a list of row dicts."""
        if not isinstance(csv_text, str):
            return []
        # Strip BOM if present (mirrors the file-path load
        # path's utf-8-sig handling).
        if csv_text.startswith(_BOM):
            csv_text = csv_text[len(_BOM):]
        reader = csv.DictReader(
            io.StringIO(csv_text), delimiter=self._delimiter
        )
        rows = [self._cast_row(dict(row)) for row in reader]
        logger.debug("Parsed %d rows from CSV string", len(rows))
        return rows

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _cast_row(row: dict[str, Any]) -> dict[str, Any]:
        """Strip whitespace from all string keys/values.

        ``csv.DictReader`` places EXTRA fields (rows with more
        columns than the header) under the ``None`` key as a
        list. Pre-audit ``k.strip()`` crashed with
        AttributeError on that ``None`` key. Now non-string
        keys are dropped entirely and non-string values are
        passed through unchanged. Audit pass 45.
        """
        if not isinstance(row, dict):
            return {}
        result: dict[str, Any] = {}
        for k, v in row.items():
            if not isinstance(k, str):
                # Skip the ``None``-key extras bucket and any
                # other non-string key.
                continue
            key = k.strip().lstrip(_BOM)
            if isinstance(v, str):
                result[key] = v.strip()
            else:
                result[key] = v
        return result

    @staticmethod
    def _apply_schema(
        row: dict[str, Any],
        schema: dict[str, type],
    ) -> dict[str, Any]:
        """Cast *row* values according to *schema*.

        Uses ``safe_float`` / ``safe_int`` from utils.helpers
        which already handle ``"$1,234.56"`` / ``"1.234,56"``
        / None / empty / garbage without crashing. Pre-audit
        reimplemented the parser inline and got European
        number format wrong (``"1.234,56"`` silently became
        ``1.23456``). Audit pass 45.
        """
        if not isinstance(row, dict) or not isinstance(schema, dict):
            return dict(row) if isinstance(row, dict) else {}
        result: dict[str, Any] = dict(row)
        for col, dtype in schema.items():
            if col not in result or result[col] is None:
                continue
            raw = result[col]
            if dtype is float:
                result[col] = safe_float(raw)
            elif dtype is int:
                result[col] = safe_int(raw)
            elif dtype is str:
                result[col] = str(raw) if raw is not None else ""
            elif dtype is bool:
                # Accept common bool-ish strings from CSVs.
                if isinstance(raw, str):
                    result[col] = raw.strip().lower() in ("true", "1", "yes", "y", "t")
                else:
                    result[col] = bool(raw)
            else:
                # Fall through to the caller-supplied type
                # constructor for any other dtype.
                result[col] = dtype(raw)
        return result
