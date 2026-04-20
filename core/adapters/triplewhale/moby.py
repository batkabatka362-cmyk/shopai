"""Triple Whale Moby Agents adapter — cross-platform MMM + recs.

Wave C-1 of IMPLEMENTATION_PLAN_2026. Per research: Moby Agents
(launched Apr 2 2026, trained on $82B GMV) produces cross-
platform budget + creative recommendations in seconds —
attempting to rebuild this internally is out of scope. Adapter-
over-build strategy.

This module wraps Moby's REST API for:
  * Pulling per-campaign recommendations (budget, status,
    creative refresh flags)
  * Submitting Shopify orders for ingestion (Moby handles
    triple-attribution internally)

Plus a novel "RL disagreement" pattern requested by the owner:
every time Moby recommends X and ShopAI's own RL votes Y, we
log ``(moby_vote, shopai_vote, actual_outcome)`` so after 30
days of data we know which source to trust per decision kind.

Narrow surface (intentional):
  * ``MobyAdapter(api_key, http=?)``
  * ``recommendations(scope="campaigns", limit=20)``
  * ``record_disagreement(decision_id, moby_vote,
    shopai_vote, note)``
  * ``update_disagreement_outcome(decision_id,
    actual_outcome)`` — closes the loop once we see revenue
  * ``win_rate_by_source()`` → summary over recorded dis-
    agreements

Auth: bearer token. Missing key → ``is_available() == False``
and every call is a logged no-op. Tests inject HTTP so the
adapter runs offline.

Docs reference:
  * triplewhale.com/blog/product-event (Apr 2 2026 launch)
  * prnewswire.com/news-releases/triple-whale-announces-
    public-launch-of-moby
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from utils.logger import get_logger


logger = get_logger("core.adapters.triplewhale.moby")


_DEFAULT_BASE = "https://api.triplewhale.com"
_DEFAULT_TIMEOUT = 15.0
_ENV_KEY = "TRIPLE_WHALE_API_KEY"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS moby_disagreements (
    disagreement_id    TEXT PRIMARY KEY,
    decision_id        TEXT NOT NULL,
    moby_vote          TEXT NOT NULL,
    shopai_vote        TEXT NOT NULL,
    actual_outcome     TEXT NOT NULL DEFAULT '',
    note               TEXT NOT NULL DEFAULT '',
    created_at         REAL NOT NULL,
    resolved_at        REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_moby_decision
    ON moby_disagreements(decision_id);
"""


@dataclass
class MobyRecommendation:
    scope: str                     # campaigns | creatives | budgets
    entity_id: str                 # campaign / adset id
    recommendation: str            # e.g. "increase_budget"
    confidence: float              # Moby's self-reported 0..1
    expected_roas_delta: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "entity_id": self.entity_id,
            "recommendation": self.recommendation,
            "confidence": round(self.confidence, 4),
            "expected_roas_delta": round(
                self.expected_roas_delta, 4,
            ),
            "raw": dict(self.raw),
        }


@dataclass
class RLDisagreementLog:
    disagreement_id: str
    decision_id: str
    moby_vote: str
    shopai_vote: str
    actual_outcome: str = ""
    note: str = ""
    created_at: float = 0.0
    resolved_at: float = 0.0

    @property
    def resolved(self) -> bool:
        return self.resolved_at > 0

    @property
    def winner(self) -> str:
        """Which source matched the actual outcome. Returns
        'both', 'moby', 'shopai', 'neither', or '' when not
        yet resolved."""
        if not self.actual_outcome:
            return ""
        moby_ok = self.moby_vote == self.actual_outcome
        shopai_ok = self.shopai_vote == self.actual_outcome
        if moby_ok and shopai_ok:
            return "both"
        if moby_ok:
            return "moby"
        if shopai_ok:
            return "shopai"
        return "neither"

    def as_dict(self) -> dict[str, Any]:
        return {
            "disagreement_id": self.disagreement_id,
            "decision_id": self.decision_id,
            "moby_vote": self.moby_vote,
            "shopai_vote": self.shopai_vote,
            "actual_outcome": self.actual_outcome,
            "note": self.note,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
            "winner": self.winner,
        }


class MobyAdapter:
    """Thin wrapper over Moby Agents + RL disagreement logger."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = _DEFAULT_BASE,
        http: Any = None,
        db_path: str | Path = "data/moby_disagreements.db",
        timeout: float = _DEFAULT_TIMEOUT,
        now_fn: Any = None,
    ) -> None:
        self._api_key = (
            api_key
            if api_key is not None
            else os.environ.get(_ENV_KEY, "")
        )
        self._base = base_url.rstrip("/")
        self._http = http
        self._timeout = float(timeout)
        self._now_fn = now_fn or time.time
        self._lock = threading.RLock()
        self._path = Path(db_path)
        self._path.parent.mkdir(
            parents=True, exist_ok=True,
        )
        self._conn = sqlite3.connect(
            str(self._path), check_same_thread=False,
        )
        with self._lock:
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()
        self._last_error = ""
        self._api_calls = 0

    def is_available(self) -> bool:
        return bool(self._api_key)

    def _client(self) -> Any:
        if self._http is not None:
            return self._http
        import requests
        return requests

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    # ── Recommendations ─────────────────────────────────

    def recommendations(
        self,
        *,
        scope: str = "campaigns",
        limit: int = 20,
    ) -> list[MobyRecommendation]:
        """Pull Moby's latest recommendations for a scope.

        Scope options per Moby docs:
          * campaigns  — per-campaign budget / status / pause
          * creatives  — creative refresh flags
          * budgets    — cross-channel reallocation
        """
        if not self.is_available():
            with self._lock:
                self._last_error = (
                    "not configured — set "
                    f"{_ENV_KEY}"
                )
            return []
        url = (
            f"{self._base}/moby/v1/recommendations"
        )
        try:
            resp = self._client().get(
                url,
                headers=self._headers(),
                params={
                    "scope": scope,
                    "limit": int(limit),
                },
                timeout=self._timeout,
            )
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._last_error = (
                    f"network: {exc}"
                )
            logger.debug(
                "moby recommendations failed: %s", exc,
            )
            return []
        status = int(
            getattr(resp, "status_code", 0),
        )
        if status >= 400:
            with self._lock:
                self._last_error = (
                    f"HTTP {status}: "
                    f"{(getattr(resp, 'text', '') or '')[:120]}"
                )
            return []
        try:
            body = resp.json()
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._last_error = (
                    f"bad JSON: {exc}"
                )
            return []
        with self._lock:
            self._api_calls += 1
            self._last_error = ""
        return self._parse_recommendations(body, scope)

    def _parse_recommendations(
        self, body: Any, scope: str,
    ) -> list[MobyRecommendation]:
        if not isinstance(body, dict):
            return []
        items = body.get("data") or body.get(
            "recommendations",
        ) or []
        if not isinstance(items, list):
            return []
        out: list[MobyRecommendation] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                out.append(MobyRecommendation(
                    scope=scope,
                    entity_id=str(
                        item.get("entity_id")
                        or item.get("id", ""),
                    ),
                    recommendation=str(
                        item.get("recommendation")
                        or item.get("action", ""),
                    ),
                    confidence=float(
                        item.get("confidence", 0)
                        or 0,
                    ),
                    expected_roas_delta=float(
                        item.get("roas_delta", 0)
                        or 0,
                    ),
                    raw=dict(item),
                ))
            except (TypeError, ValueError) as exc:
                logger.debug(
                    "skip malformed rec: %s", exc,
                )
        return out

    # ── Disagreement log (owner-requested option 3) ─────

    def record_disagreement(
        self,
        *,
        decision_id: str,
        moby_vote: str,
        shopai_vote: str,
        note: str = "",
    ) -> RLDisagreementLog:
        """Log a case where Moby and ShopAI's RL voted
        differently. Resolve later with
        ``update_disagreement_outcome``."""
        if not decision_id:
            raise ValueError("decision_id required")
        if moby_vote == shopai_vote:
            raise ValueError(
                "votes agree — this isn't a disagreement",
            )
        now = float(self._now_fn())
        did = uuid.uuid4().hex
        with self._lock:
            self._conn.execute(
                "INSERT INTO moby_disagreements("
                "disagreement_id, decision_id, "
                "moby_vote, shopai_vote, note, "
                "created_at) VALUES(?, ?, ?, ?, ?, ?)",
                (
                    did, decision_id, moby_vote,
                    shopai_vote, note, now,
                ),
            )
            self._conn.commit()
        return RLDisagreementLog(
            disagreement_id=did,
            decision_id=decision_id,
            moby_vote=moby_vote,
            shopai_vote=shopai_vote,
            note=note,
            created_at=now,
        )

    def update_disagreement_outcome(
        self,
        *,
        decision_id: str,
        actual_outcome: str,
    ) -> bool:
        """Resolve a logged disagreement with the actual
        outcome. Returns True if a row was updated."""
        if not decision_id:
            raise ValueError("decision_id required")
        now = float(self._now_fn())
        with self._lock:
            n = self._conn.execute(
                "UPDATE moby_disagreements SET "
                "actual_outcome=?, resolved_at=? "
                "WHERE decision_id=? AND resolved_at=0",
                (actual_outcome, now, decision_id),
            ).rowcount
            self._conn.commit()
        return bool(n)

    def recent_disagreements(
        self, *, limit: int = 50,
    ) -> list[RLDisagreementLog]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT disagreement_id, decision_id, "
                "moby_vote, shopai_vote, "
                "actual_outcome, note, "
                "created_at, resolved_at "
                "FROM moby_disagreements "
                "ORDER BY created_at DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [
            RLDisagreementLog(
                disagreement_id=r[0],
                decision_id=r[1],
                moby_vote=r[2],
                shopai_vote=r[3],
                actual_outcome=r[4],
                note=r[5],
                created_at=float(r[6]),
                resolved_at=float(r[7]),
            )
            for r in rows
        ]

    def win_rate_by_source(self) -> dict[str, Any]:
        """Summarise how often Moby / ShopAI / both matched
        the actual outcome over all resolved disagreements."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT moby_vote, shopai_vote, "
                "actual_outcome FROM moby_disagreements "
                "WHERE resolved_at > 0",
            ).fetchall()
        total = len(rows)
        moby_wins = 0
        shopai_wins = 0
        both = 0
        neither = 0
        for moby, shopai, actual in rows:
            moby_ok = moby == actual
            shopai_ok = shopai == actual
            if moby_ok and shopai_ok:
                both += 1
            elif moby_ok:
                moby_wins += 1
            elif shopai_ok:
                shopai_wins += 1
            else:
                neither += 1
        return {
            "total_resolved": total,
            "moby_only": moby_wins,
            "shopai_only": shopai_wins,
            "both_correct": both,
            "both_wrong": neither,
            "moby_win_rate": (
                (moby_wins + both) / total
                if total else 0.0
            ),
            "shopai_win_rate": (
                (shopai_wins + both) / total
                if total else 0.0
            ),
        }

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "adapter": "moby",
                "configured": bool(self._api_key),
                "api_calls": self._api_calls,
                "last_error": self._last_error,
            }

    def close(self) -> None:
        with self._lock:
            self._conn.close()
