"""CSVLoader — loads CSV files into lists of dicts with optional schema validation.

Uses only the Python standard library (``csv`` module).
"""
from __future__ import annotations

import csv
import io
import logging
import os
from typing import Any

logger = logging.getLogger("data_pipeline.csv_loader")


class CSVLoaderError(Exception):
    """Raised for unrecoverable CSV loading errors."""


class CSVLoader:
    """Loads CSV files into ``list[dict]`` with optional column validation.

    Args:
        delimiter: Field delimiter character (default ``,``).
        encoding:  File encoding (default ``utf-8``).
    """

    def __init__(self, delimiter: str = ",", encoding: str = "utf-8") -> None:
        self._delimiter = delimiter
        self._encoding = encoding

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
            CSVLoaderError: If the file cannot be opened.
        """
        filepath = os.path.expanduser(filepath)
        if not os.path.isfile(filepath):
            raise CSVLoaderError(f"File not found: {filepath}")

        try:
            with open(filepath, newline="", encoding=self._encoding) as fh:
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
        if not rows:
            return list(required_columns)

        present = set(rows[0].keys())
        missing = [col for col in required_columns if col not in present]
        if missing:
            logger.warning("Missing columns: %s", missing)
        return missing

    # ------------------------------------------------------------------
    # Convenience: load from a string
    # ------------------------------------------------------------------

    def load_string(self, csv_text: str) -> list[dict[str, Any]]:
        """Parse *csv_text* as CSV content and return a list of row dicts."""
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
    def _cast_row(row: dict[str, str]) -> dict[str, Any]:
        """Strip whitespace from all string values."""
        return {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()}

    @staticmethod
    def _apply_schema(
        row: dict[str, Any],
        schema: dict[str, type],
    ) -> dict[str, Any]:
        """Cast *row* values according to *schema*.

        Raises:
            ValueError / TypeError: propagated from type constructors.
        """
        result: dict[str, Any] = dict(row)
        for col, dtype in schema.items():
            if col in result and result[col] is not None:
                raw = result[col]
                if dtype is float:
                    # Handle currency strings like "$1,234.56"
                    import re
                    cleaned = re.sub(r"[^\d.\-]", "", str(raw).replace(",", ""))
                    result[col] = float(cleaned) if cleaned else 0.0
                elif dtype is int:
                    import re
                    cleaned = re.sub(r"[^\d\-]", "", str(raw).replace(",", ""))
                    result[col] = int(cleaned) if cleaned else 0
                else:
                    result[col] = dtype(raw)
        return result
