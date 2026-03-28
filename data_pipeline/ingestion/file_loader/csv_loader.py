"""CSV Loader — loads and parses CSV files into structured data."""
from __future__ import annotations
import csv
import io
from typing import Any
from utils.logger import get_logger

logger = get_logger("data.csv_loader")


class CSVLoader:
    """Loads CSV files into list of dicts."""

    def load_file(self, file_path: str) -> list[dict[str, Any]]:
        logger.info("Loading CSV: %s", file_path)
        try:
            with open(file_path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                return list(reader)
        except FileNotFoundError:
            logger.error("File not found: %s", file_path)
            return []

    def load_string(self, csv_string: str) -> list[dict[str, Any]]:
        reader = csv.DictReader(io.StringIO(csv_string))
        return list(reader)
