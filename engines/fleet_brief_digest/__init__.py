"""Fleet Brief Digest Engine — W963-41 (PHASE 2 CAPSTONE).

Single morning command. Synthesizes the entire empire state
into a one-screen brief:

  - Fleet headline verdict (intervene / earning / cold-start /
    quiet)
  - Top interventions (W963-40)
  - Top earnings stores (W963-19 + fleet)
  - Substrate health summary
  - Today's top 3 strategic actions

Designed to be the operator's first command of the day. The
W963-35 fleet_strategist gives ranked stores; W963-40 gives
critical signals; THIS engine combines them into the
narrative-style "here's what you need to know."

Bible scoring:
  Q1 (20-store leverage): operator scans ONE digest, knows
     fleet state, picks the 1-3 actions that matter. At
     20 stores, 5 minutes of attention manages the empire.
  Q2 (substrate composability): pure synthesis -- composes
     fleet_strategist + fleet_intervention_alerts +
     fleet_emergency_pause + autopilot status + chaos
     verdict + earnings_by_engine. Zero new substrate.

CLI:
  shopai brief              -- one-screen morning digest
  shopai brief --json
"""
from .flow import FleetBriefDigestEngine

__all__ = ["FleetBriefDigestEngine"]
