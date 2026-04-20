"""Risk tripwire — hard $-based safety caps for live execution.

Sprint 3 S3-1 (P0, L7 in docs/AGI_STACK.md). Unlike `core/brain/
risk_budget.py` which tracks abstract *risk units* per category,
this module enforces **concrete dollar limits at the exact moment**
a live write is about to happen:

    verdict = tripwire.check_before_spend(
        amount_usd=20.0,
        category="ad_spend",
        context={"campaign_id": "cmp_1"},
    )
    if verdict.action == "block":
        raise TripwireBlocked(verdict.reason)

Four caps enforced:

  * ``daily_ad_spend_usd``    — total ad $ across all campaigns / UTC day
  * ``per_campaign_cap_usd``  — single-campaign $ budget ceiling
  * ``min_margin_ratio``      — reject low-margin product if declared
  * ``max_chargeback_rate``   — halt live flow if chargebacks spike

Env overrides (numeric, optional):
  * ``SHOPAI_RISK_DAILY_CAP_USD``
  * ``SHOPAI_RISK_PER_CAMPAIGN_CAP_USD``
  * ``SHOPAI_RISK_MIN_MARGIN``
  * ``SHOPAI_RISK_MAX_CHARGEBACK``
  * ``SHOPAI_RISK_ESCALATE_PCT``   — escalate (not block) above this
    fraction of the daily cap (default 0.8 → 80%)

Storage: SQLite (``data/risk_tripwire.db``) — one row per recorded
spend + one row per recorded chargeback outcome. Daily rollup is a
simple SUM query over the last 24 hours (wall-clock UTC).

Idempotency: ``check_before_spend`` is read-only. ``record_spend``
accepts a ``dedupe_key`` — repeat call with same key is a no-op.

Pure stdlib. Thread-safe (Lock). Deterministic. LLM-free. Zero cost.
"""
from __future__ import annotations

import calendar
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


logger = get_logger("core.risk.tripwire")


# ── Defaults ─────────────────────────────────────────────────

_DEFAULT_DAILY_CAP = 50.0
_DEFAULT_PER_CAMPAIGN_CAP = 20.0
_DEFAULT_MIN_MARGIN = 0.10
_DEFAULT_MAX_CHARGEBACK = 0.01
_DEFAULT_ESCALATE_PCT = 0.8
_CHARGEBACK_LOOKBACK_DAYS = 30


# ── Schema ───────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS risk_spend (
    id          TEXT PRIMARY KEY,
    ts          REAL NOT NULL,
    category    TEXT NOT NULL,
    amount_usd  REAL NOT NULL,
    campaign_id TEXT NOT NULL DEFAULT '',
    dedupe_key  TEXT NOT NULL DEFAULT '',
    meta        TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_risk_spend_ts
    ON risk_spend(ts);
CREATE INDEX IF NOT EXISTS idx_risk_spend_campaign
    ON risk_spend(campaign_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_risk_spend_dedupe
    ON risk_spend(dedupe_key)
    WHERE dedupe_key <> '';

CREATE TABLE IF NOT EXISTS risk_outcome (
    id       TEXT PRIMARY KEY,
    ts       REAL NOT NULL,
    kind     TEXT NOT NULL,
    is_bad   INTEGER NOT NULL,
    meta     TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_risk_outcome_ts
    ON risk_outcome(ts);
"""


# ── Config dataclass ─────────────────────────────────────────


@dataclass
class TripwireLimits:
    """Hard caps. All values positive. 0 or negative = disabled."""

    daily_ad_spend_usd: float = _DEFAULT_DAILY_CAP
    per_campaign_cap_usd: float = _DEFAULT_PER_CAMPAIGN_CAP
    min_margin_ratio: float = _DEFAULT_MIN_MARGIN
    max_chargeback_rate: float = _DEFAULT_MAX_CHARGEBACK
    escalate_pct: float = _DEFAULT_ESCALATE_PCT

    @classmethod
    def from_env(cls) -> TripwireLimits:
        def _f(name: str, default: float) -> float:
            raw = os.environ.get(name, "")
            if not raw:
                return default
            try:
                return float(raw)
            except ValueError:
                logger.warning(
                    "invalid env %s=%r — using default %s",
                    name, raw, default,
                )
                return default
        return cls(
            daily_ad_spend_usd=_f(
                "SHOPAI_RISK_DAILY_CAP_USD",
                _DEFAULT_DAILY_CAP,
            ),
            per_campaign_cap_usd=_f(
                "SHOPAI_RISK_PER_CAMPAIGN_CAP_USD",
                _DEFAULT_PER_CAMPAIGN_CAP,
            ),
            min_margin_ratio=_f(
                "SHOPAI_RISK_MIN_MARGIN",
                _DEFAULT_MIN_MARGIN,
            ),
            max_chargeback_rate=_f(
                "SHOPAI_RISK_MAX_CHARGEBACK",
                _DEFAULT_MAX_CHARGEBACK,
            ),
            escalate_pct=_f(
                "SHOPAI_RISK_ESCALATE_PCT",
                _DEFAULT_ESCALATE_PCT,
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "daily_ad_spend_usd": round(
                self.daily_ad_spend_usd, 2,
            ),
            "per_campaign_cap_usd": round(
                self.per_campaign_cap_usd, 2,
            ),
            "min_margin_ratio": round(self.min_margin_ratio, 4),
            "max_chargeback_rate": round(
                self.max_chargeback_rate, 4,
            ),
            "escalate_pct": round(self.escalate_pct, 4),
        }


# ── Verdict ──────────────────────────────────────────────────


@dataclass
class TripwireVerdict:
    action: str          # "allow" | "escalate" | "block"
    reason: str = ""
    rule: str = ""       # which cap triggered
    context: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "reason": self.reason,
            "rule": self.rule,
            "context": dict(self.context),
        }


class TripwireBlocked(Exception):
    """Raised when a write path is hard-blocked by tripwire."""

    def __init__(self, verdict: TripwireVerdict) -> None:
        super().__init__(verdict.reason or "blocked by tripwire")
        self.verdict = verdict


# ── Main class ───────────────────────────────────────────────


class RiskTripwire:
    """Concrete $-cap safety gate for live execution."""

    def __init__(
        self,
        db_path: str | Path = "data/risk_tripwire.db",
        *,
        limits: TripwireLimits | None = None,
        now_fn: Any = None,
    ) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._limits = limits or TripwireLimits.from_env()
        self._now_fn = now_fn or time.time
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(
            str(self._path), check_same_thread=False,
        )
        with self._lock:
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    # ── Limits ───────────────────────────────────────────

    def limits(self) -> TripwireLimits:
        return self._limits

    def set_limits(self, limits: TripwireLimits) -> None:
        self._limits = limits

    # ── Check ────────────────────────────────────────────

    def check_before_spend(
        self,
        *,
        amount_usd: float,
        category: str = "ad_spend",
        campaign_id: str = "",
        margin_ratio: float | None = None,
        context: dict[str, Any] | None = None,
    ) -> TripwireVerdict:
        """Read-only pre-spend gate. Never mutates state.

        Returns verdict.action ∈ ``allow`` | ``escalate`` | ``block``.
        ``escalate`` means owner-approval needed (soft), ``block``
        means refuse (hard).
        """
        ctx = dict(context or {})
        amount = float(amount_usd)
        if amount < 0:
            return TripwireVerdict(
                action="block",
                reason="negative amount",
                rule="amount_sanity",
                context=ctx,
            )

        # 1. Margin floor (product-level, pre-emptive)
        margin_verdict = self._check_margin(
            margin_ratio, ctx,
        )
        if margin_verdict is not None:
            return margin_verdict

        # 2. Chargeback rate (account-level, pre-emptive)
        cb_verdict = self._check_chargeback_rate(ctx)
        if cb_verdict is not None:
            return cb_verdict

        # 3. Per-campaign cap
        pc_verdict = self._check_per_campaign_cap(
            amount, campaign_id, ctx,
        )
        if pc_verdict is not None:
            return pc_verdict

        # 4. Daily ad-spend cap
        day_verdict = self._check_daily_cap(
            amount, category, ctx,
        )
        if day_verdict is not None:
            return day_verdict

        return TripwireVerdict(
            action="allow",
            reason="within all limits",
            rule="",
            context=ctx,
        )

    def _check_margin(
        self,
        margin_ratio: float | None,
        ctx: dict[str, Any],
    ) -> TripwireVerdict | None:
        cap = self._limits.min_margin_ratio
        if cap <= 0 or margin_ratio is None:
            return None
        try:
            m = float(margin_ratio)
        except (TypeError, ValueError):
            return TripwireVerdict(
                action="block",
                reason=(
                    f"invalid margin_ratio={margin_ratio!r}"
                ),
                rule="min_margin_ratio",
                context=ctx,
            )
        if m < cap:
            return TripwireVerdict(
                action="block",
                reason=(
                    f"margin {m:.2%} below floor "
                    f"{cap:.2%}"
                ),
                rule="min_margin_ratio",
                context={**ctx, "margin_ratio": m, "floor": cap},
            )
        return None

    def _check_chargeback_rate(
        self, ctx: dict[str, Any],
    ) -> TripwireVerdict | None:
        cap = self._limits.max_chargeback_rate
        if cap <= 0:
            return None
        total, bad = self._outcome_rate(
            lookback_days=_CHARGEBACK_LOOKBACK_DAYS,
        )
        if total < 20:
            # Not enough volume to judge — allow.
            return None
        rate = bad / total if total > 0 else 0.0
        if rate > cap:
            return TripwireVerdict(
                action="block",
                reason=(
                    f"chargeback rate {rate:.2%} "
                    f"> cap {cap:.2%} "
                    f"({bad}/{total} last "
                    f"{_CHARGEBACK_LOOKBACK_DAYS}d)"
                ),
                rule="max_chargeback_rate",
                context={
                    **ctx,
                    "chargeback_rate": rate,
                    "bad": bad,
                    "total": total,
                },
            )
        return None

    def _check_per_campaign_cap(
        self,
        amount: float,
        campaign_id: str,
        ctx: dict[str, Any],
    ) -> TripwireVerdict | None:
        cap = self._limits.per_campaign_cap_usd
        if cap <= 0 or amount <= 0 or not campaign_id:
            return None
        today_spent = self._campaign_daily_spend(campaign_id)
        projected = today_spent + amount
        if projected > cap:
            return TripwireVerdict(
                action="block",
                reason=(
                    f"campaign {campaign_id} daily "
                    f"${today_spent:.2f}+${amount:.2f} "
                    f"> cap ${cap:.2f}"
                ),
                rule="per_campaign_cap_usd",
                context={
                    **ctx,
                    "today_spent": today_spent,
                    "projected": projected,
                    "cap": cap,
                    "campaign_id": campaign_id,
                },
            )
        return None

    def _check_daily_cap(
        self,
        amount: float,
        category: str,
        ctx: dict[str, Any],
    ) -> TripwireVerdict | None:
        cap = self._limits.daily_ad_spend_usd
        if cap <= 0 or amount <= 0 or category != "ad_spend":
            return None
        today_spent = self._daily_spend(category)
        projected = today_spent + amount
        if projected > cap:
            return TripwireVerdict(
                action="block",
                reason=(
                    f"daily {category} "
                    f"${today_spent:.2f}+${amount:.2f} "
                    f"> cap ${cap:.2f}"
                ),
                rule="daily_ad_spend_usd",
                context={
                    **ctx,
                    "today_spent": today_spent,
                    "projected": projected,
                    "cap": cap,
                },
            )
        escalate = cap * max(0.0, min(1.0, self._limits.escalate_pct))
        if escalate > 0 and projected > escalate:
            return TripwireVerdict(
                action="escalate",
                reason=(
                    f"daily {category} projected "
                    f"${projected:.2f} > {self._limits.escalate_pct:.0%} "
                    f"of cap ${cap:.2f}"
                ),
                rule="daily_ad_spend_usd_escalate",
                context={
                    **ctx,
                    "today_spent": today_spent,
                    "projected": projected,
                    "cap": cap,
                },
            )
        return None

    # ── Record ───────────────────────────────────────────

    def record_spend(
        self,
        *,
        amount_usd: float,
        category: str = "ad_spend",
        campaign_id: str = "",
        dedupe_key: str = "",
        meta: dict[str, Any] | None = None,
    ) -> str:
        """Append a spend event. Returns event id.

        ``dedupe_key`` makes the call idempotent — a repeated call
        with the same key is a no-op and returns the original id.
        """
        if amount_usd < 0:
            raise ValueError("amount_usd must be ≥ 0")
        amount = float(amount_usd)
        now = float(self._now_fn())
        meta_json = json.dumps(meta or {}, sort_keys=True)
        key = str(dedupe_key).strip()
        with self._lock:
            if key:
                row = self._conn.execute(
                    "SELECT id FROM risk_spend "
                    "WHERE dedupe_key=?",
                    (key,),
                ).fetchone()
                if row is not None:
                    return str(row[0])
            eid = uuid.uuid4().hex
            self._conn.execute(
                "INSERT INTO risk_spend"
                "(id, ts, category, amount_usd, campaign_id, "
                " dedupe_key, meta) VALUES"
                "(?, ?, ?, ?, ?, ?, ?)",
                (
                    eid, now, str(category), amount,
                    str(campaign_id), key, meta_json,
                ),
            )
            self._conn.commit()
        return eid

    def record_outcome(
        self,
        *,
        kind: str,
        is_bad: bool,
        meta: dict[str, Any] | None = None,
    ) -> str:
        """Record a transaction outcome for chargeback tracking.

        ``kind`` = "order" | "chargeback" | "refund" | ...;
        ``is_bad`` True for chargeback/fraud, False for clean orders.
        """
        if not kind:
            raise ValueError("kind required")
        now = float(self._now_fn())
        meta_json = json.dumps(meta or {}, sort_keys=True)
        eid = uuid.uuid4().hex
        with self._lock:
            self._conn.execute(
                "INSERT INTO risk_outcome"
                "(id, ts, kind, is_bad, meta) VALUES"
                "(?, ?, ?, ?, ?)",
                (eid, now, str(kind), 1 if is_bad else 0, meta_json),
            )
            self._conn.commit()
        return eid

    # ── Rollup ───────────────────────────────────────────

    def _day_bounds(self) -> tuple[float, float]:
        """UTC day [start, end) around now."""
        now = float(self._now_fn())
        t = time.gmtime(now)
        start = calendar.timegm((
            t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, 0,
        ))
        return float(start), float(start + 86400.0)

    def _daily_spend(self, category: str) -> float:
        start, end = self._day_bounds()
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(SUM(amount_usd), 0) "
                "FROM risk_spend "
                "WHERE category=? AND ts>=? AND ts<?",
                (category, start, end),
            ).fetchone()
        return float(row[0] or 0.0)

    def _campaign_daily_spend(
        self, campaign_id: str,
    ) -> float:
        start, end = self._day_bounds()
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(SUM(amount_usd), 0) "
                "FROM risk_spend "
                "WHERE campaign_id=? AND ts>=? AND ts<?",
                (campaign_id, start, end),
            ).fetchone()
        return float(row[0] or 0.0)

    def _outcome_rate(
        self, *, lookback_days: int,
    ) -> tuple[int, int]:
        cutoff = float(self._now_fn()) - (
            int(lookback_days) * 86400.0
        )
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*), "
                "COALESCE(SUM(is_bad), 0) "
                "FROM risk_outcome WHERE ts >= ?",
                (cutoff,),
            ).fetchone()
        total = int(row[0] or 0)
        bad = int(row[1] or 0)
        return total, bad

    # ── Status ───────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        start, end = self._day_bounds()
        daily = self._daily_spend("ad_spend")
        cap = self._limits.daily_ad_spend_usd
        util = (daily / cap) if cap > 0 else 0.0
        total, bad = self._outcome_rate(
            lookback_days=_CHARGEBACK_LOOKBACK_DAYS,
        )
        return {
            "limits": self._limits.as_dict(),
            "today": {
                "window_start": start,
                "window_end": end,
                "ad_spend_usd": round(daily, 2),
                "utilisation": round(util, 4),
                "remaining_usd": round(
                    max(0.0, cap - daily), 2,
                ),
            },
            "chargebacks": {
                "window_days": _CHARGEBACK_LOOKBACK_DAYS,
                "total": total,
                "bad": bad,
                "rate": round(
                    (bad / total) if total > 0 else 0.0, 4,
                ),
            },
        }

    def recent_spend(
        self, *, limit: int = 50,
    ) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, ts, category, amount_usd, "
                "campaign_id, meta FROM risk_spend "
                "ORDER BY ts DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            try:
                meta = json.loads(r[5] or "{}")
            except (TypeError, ValueError):
                meta = {}
            out.append({
                "id": r[0],
                "ts": float(r[1]),
                "category": r[2],
                "amount_usd": round(float(r[3]), 2),
                "campaign_id": r[4],
                "meta": meta,
            })
        return out

    def stats(self) -> dict[str, Any]:
        with self._lock:
            spend = int(self._conn.execute(
                "SELECT COUNT(*) FROM risk_spend",
            ).fetchone()[0])
            outcomes = int(self._conn.execute(
                "SELECT COUNT(*) FROM risk_outcome",
            ).fetchone()[0])
        return {
            "spend_events": spend,
            "outcome_events": outcomes,
        }

    def close(self) -> None:
        with self._lock:
            self._conn.close()


# ── Facade singleton ─────────────────────────────────────────

_SINGLETON: RiskTripwire | None = None
_SINGLETON_LOCK = threading.Lock()


def get_risk_tripwire() -> RiskTripwire:
    global _SINGLETON
    if _SINGLETON is None:
        with _SINGLETON_LOCK:
            if _SINGLETON is None:
                _SINGLETON = RiskTripwire()
    return _SINGLETON


def reset_risk_tripwire_for_tests() -> None:
    """Test-only helper — clears the module-level singleton."""
    global _SINGLETON
    with _SINGLETON_LOCK:
        if _SINGLETON is not None:
            try:
                _SINGLETON.close()
            except Exception:  # noqa: BLE001
                pass
        _SINGLETON = None
