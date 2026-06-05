"""AGI Recommend Streak — W963-70 (operator-attention guard).

Counts consecutive snapshots where the system has been
SIGNALING a problem but the operator hasn't taken
substantive action.

Three streak classes:
  loss_streak           consecutive snapshots with verdict
                        in {attributed_loss, organic_only}
                        AND no executed actions in the
                        approval queue since the streak
                        began.
  no_data_streak        consecutive snapshots with
                        verdict=no_data (empire idle --
                        cron may be broken).
  anomaly_streak        consecutive snapshots where the
                        anomaly detector reported >=1
                        critical anomaly.

Each streak emits:
  count       int  consecutive snapshots
  severity    info / warn / critical (escalating with N)
  drill       str  exact CLI command to address it

A separate ATTENTION_NEEDED top-line surfaces the worst.

Pattern J + Pattern Q.

CLI:
  shopai attention [--threshold-days N] [--json]
"""
from .flow import AgiRecommendStreakEngine

__all__ = ["AgiRecommendStreakEngine"]
