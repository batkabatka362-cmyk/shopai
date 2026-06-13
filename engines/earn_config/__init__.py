"""Earn Config Wizard — W963-87 (config bootstrap).

The 9 go-live warnings each tell the operator what env-var
to set, but they have to set each individually. This engine
ships a single command that:

  1. Reads the current go-live warnings.
  2. Maps each warning to its corresponding env-var(s).
  3. Optionally writes sensible defaults to .env (or
     prints them for the operator to paste).

Three modes:
  --inspect   show the env-var change-list (default)
  --apply     write the changes to ./.env (idempotent)
  --print     print the export commands for shell paste

Safe defaults:
  SHOPAI_SPEND_CAP_DAILY_USD=50          ($50/day cap)
  SHOPAI_AUTO_PAUSE_ON_OVERSPEND=1       (auto-pause on cap)
  SHOPAI_AUTO_QUARANTINE_FROM_REVENUE=1  (quarantine bad engines)
  SHOPAI_AUTO_DISARM_ON_OVERRIDE=1       (W963-82 auto-disarm)
  SHOPAI_CYCLE_RECORD_BRIEF=1            (self-bootstrap snapshots)
  SHOPAI_AI_STRATEGY=1                   (LLM advisor on)
  SHOPAI_NOTIFY_AUTONOMY_COALESCE=1      (alert rollup)

Webhook URL + OpenAI key NOT defaulted (operator-specific).

Pattern J + Pattern Q.

CLI:
  shopai earn-config              # inspect
  shopai earn-config --apply      # write .env
  shopai earn-config --print      # print export commands
  shopai earn-config --json
"""
from .flow import EarnConfigEngine

__all__ = ["EarnConfigEngine"]
