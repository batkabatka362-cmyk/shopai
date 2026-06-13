"""AGI Earnings History — W963-50 (Phase 3.A epilogue).

Persistent log of `agi_earnings_summary` verdicts so the
operator can answer not just "is the AGI earning RIGHT
NOW?" but "is the AGI's earning getting BETTER over time?"

Mirrors the W963-46 pattern (snapshot persistence + trend
verdict) but operates at the COMPOSED-verdict layer:

  snapshot:  {ts, days, verdict, gross_profit, attr_pct,
              monthly_run_rate, trend_verdict, store_count}

Trend verdict (across N daily snapshots):
  improving      consecutive verdicts trending toward earning
  declining      verdicts trending away from earning
  flat           same verdict band most of window
  no_data        <2 snapshots

Pattern J guard: short-circuits under pytest unless override.

CLI:
  shopai earnings-history --record           -- snapshot now
  shopai earnings-history                    -- summary
  shopai earnings-history --trend [--days N]
  shopai earnings-history --query [--days N] [--limit N]
  shopai earnings-history --json
"""
from .flow import AgiEarningsHistoryEngine

__all__ = ["AgiEarningsHistoryEngine"]
