"""Fleet Notifier Engine — W963-42.

Pushes critical empire events to operator notification channel
(webhook, Slack, etc.) when they fire. Closes the asynchronous
loop: brief is pull-only, this engine is push.

Fires on:
  - Fleet emergency activation (W963-32)
  - Critical anomaly outliers (W963-33)
  - Auto-quarantine actions (W963-38)
  - Fleet intervention critical alerts (W963-40)
  - Engine error verdicts on autopilot bridge
  - Calibrator blocked-band engines (W963-39)

Per-event cooldown so the same event doesn't spam the channel
(e.g. fleet_emergency once per 24h max). Cooldown state lives
in data/fleet_notifier_state.json.

Bible scoring:
  Q1 (20-store leverage): operator can step away from terminal;
     critical events page them automatically.
  Q4 (resilience): degraded substrate signals reach the
     operator without requiring them to poll.

Composes:
  - existing engines/_notify.py substrate
  - fleet_intervention_alerts (W963-40) for the signal feed
  - fleet_brief_digest (W963-41) for the message body

CLI:
  shopai notify-fleet               -- dry-run (no send)
  shopai notify-fleet --yes         -- live (post to webhook)
  shopai notify-fleet --kind X      -- send only one kind
  shopai notify-fleet --reset       -- clear cooldowns
  shopai notify-fleet --json
"""
from .flow import FleetNotifierEngine

__all__ = ["FleetNotifierEngine"]
