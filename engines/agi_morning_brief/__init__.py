"""AGI Morning Brief — W963-54 (Phase 4 opener).

The 10-second morning standup. Composes EVERY Phase 3
substrate engine into one operator-facing report:

  - W963-48 agi_earnings_summary    -> verdict + run-rate
  - W963-50 agi_earnings_history    -> 14d trend
  - W963-47 revenue_reconciliation  -> orphan count
  - W963-52 llm_action_proposer     -> next 3 actions
  - W963-53 llm_action_critic       -> critique of plan
  - approval queue                  -> pending count
  - cycle_history latest            -> last cycle health
  - W963-50 records snapshot         -> daily-cron pattern

One command. One screen. Operator's morning question
("what's the state, what do I do?") answered without
chaining 5 commands.

Pattern J + Pattern Q.

CLI:
  shopai morning-brief
  shopai morning-brief --store STORE
  shopai morning-brief --record   # also persist W963-50 snap
  shopai morning-brief --json
"""
from .flow import AgiMorningBriefEngine

__all__ = ["AgiMorningBriefEngine"]
