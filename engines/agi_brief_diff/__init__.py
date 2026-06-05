"""AGI Brief Diff — W963-68 (Phase 4 operator UX).

Answers "what changed since the last morning brief?" by
comparing today's W963-50 snapshot vs the prior one.

Reads the two newest snapshots from
agi_earnings_history.store.query. Computes:
  - verdict transition (none / improved / regressed / shifted)
  - gross_profit delta (USD)
  - attribution_pct delta (percentage points)
  - monthly_run_rate delta
  - history-trend transition

Headline summarises with verbs:
  no_data           need at least 2 snapshots; --record
  unchanged         same verdict + within $1 / 0.5pp drift
  improved          new verdict ranks higher OR profit
                    up + significant (>$5 absolute and
                    >5% relative)
  regressed         new verdict ranks lower OR profit
                    down significantly
  shifted           verdict band changed within the same
                    rank (e.g. organic_only -> earning
                    counts as improved, but earning ->
                    earning with -$10 profit counts as
                    regressed if magnitude justifies)

Pattern J + Pattern Q.

CLI:
  shopai brief-diff [--json]
"""
from .flow import AgiBriefDiffEngine

__all__ = ["AgiBriefDiffEngine"]
