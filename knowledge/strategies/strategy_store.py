"""Strategy Store -- reusable business strategy storage with rating and persistence."""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

_PERSIST_PATH = "/tmp/shopai_strategies.json"


class StrategyStore:
    """Store, retrieve, search, and rate reusable business strategies."""

    def __init__(self, persist_path: str = _PERSIST_PATH) -> None:
        self._persist_path = persist_path
        # _strategies maps name -> {
        #   "name", "description", "steps", "conditions",
        #   "expected_outcome", "category", "ratings", "created_at", "updated_at"
        # }
        self._strategies: dict[str, dict[str, Any]] = {}
        self._load()

    # ---- CRUD ----------------------------------------------------------

    def store(self, strategy_name: str, strategy: dict) -> None:
        """Store a strategy.

        Expected keys in *strategy*: description, steps, conditions,
        expected_outcome.  Optional: category.
        """
        now = time.time()
        self._strategies[strategy_name] = {
            "name": strategy_name,
            "description": strategy.get("description", ""),
            "steps": strategy.get("steps", []),
            "conditions": strategy.get("conditions", {}),
            "expected_outcome": strategy.get("expected_outcome", ""),
            "category": strategy.get("category", "general"),
            "ratings": strategy.get("ratings", []),
            "created_at": now,
            "updated_at": now,
        }
        self._persist()

    def retrieve(self, strategy_name: str) -> dict:
        if strategy_name not in self._strategies:
            raise KeyError(f"Strategy '{strategy_name}' not found")
        return self._strategies[strategy_name]

    def delete(self, strategy_name: str) -> bool:
        removed = self._strategies.pop(strategy_name, None) is not None
        if removed:
            self._persist()
        return removed

    # ---- Listing / search -----------------------------------------------

    def list_strategies(self, category: str | None = None) -> list[dict]:
        results: list[dict] = []
        for s in self._strategies.values():
            if category is not None and s.get("category") != category:
                continue
            results.append(s)
        return results

    def search(self, query: str) -> list[dict]:
        """Keyword search across name and description (case-insensitive)."""
        q = query.lower()
        matches: list[dict] = []
        for s in self._strategies.values():
            text = f"{s['name']} {s.get('description', '')}".lower()
            if q in text:
                matches.append(s)
        return matches

    # ---- Rating --------------------------------------------------------

    def rate(self, strategy_name: str, rating: float, feedback: str = "") -> None:
        if strategy_name not in self._strategies:
            raise KeyError(f"Strategy '{strategy_name}' not found")
        entry = self._strategies[strategy_name]
        entry.setdefault("ratings", []).append({
            "rating": rating,
            "feedback": feedback,
            "timestamp": time.time(),
        })
        entry["updated_at"] = time.time()
        self._persist()

    def get_top_rated(self, n: int = 5, category: str | None = None) -> list[dict]:
        """Return top-*n* strategies by average rating."""
        candidates = self.list_strategies(category)

        def _avg_rating(s: dict) -> float:
            ratings = s.get("ratings", [])
            if not ratings:
                return 0.0
            return sum(r["rating"] for r in ratings) / len(ratings)

        candidates.sort(key=_avg_rating, reverse=True)
        return candidates[:n]

    # ---- Persistence ---------------------------------------------------

    def _persist(self) -> None:
        try:
            with open(self._persist_path, "w") as f:
                json.dump(self._strategies, f, indent=2)
        except OSError as exc:
            logger.warning(
                "StrategyStore._persist failed (%s): %s",
                self._persist_path, exc,
            )

    def _load(self) -> None:
        if not os.path.exists(self._persist_path):
            return
        try:
            with open(self._persist_path) as f:
                self._strategies = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(
                "StrategyStore._load failed (%s): %s",
                self._persist_path, exc,
            )
