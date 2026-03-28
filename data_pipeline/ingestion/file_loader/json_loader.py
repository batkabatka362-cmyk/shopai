"""JSON Loader — loads and parses JSON files into structured data."""
from __future__ import annotations
import json
from typing import Any
from utils.logger import get_logger

logger = get_logger("data.json_loader")


class JSONLoader:
    """Loads JSON files into Python objects."""

    def load_file(self, file_path: str) -> Any:
        logger.info("Loading JSON: %s", file_path)
        try:
            with open(file_path, encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            logger.error("File not found: %s", file_path)
            return {}

    def load_string(self, json_string: str) -> Any:
        return json.loads(json_string)
