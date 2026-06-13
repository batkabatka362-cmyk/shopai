"""Fleet Emergency Pause Engine — W963-32.

Single-command kill switch. When a fleet-wide anomaly fires
(catastrophic refund spike, fraud detection trigger, runaway
ad spend, accidental email blast, etc.), halt ALL autonomy
across ALL stores in one command.

Composes the existing W963-23 autopilot env gates + the
Phase 12+ autonomy_bulk substrate + adds a top-level
SHOPAI_FLEET_EMERGENCY_PAUSE marker that all autopilot writers
consult before firing.

Bible scoring:
  Q1 (20-store leverage): one command halts 20 stores; without
     it, operator manually disables each store.
  Q4 (resilience): the canonical "stop everything" lever.
     Defense-in-depth: even if individual env gates leak or
     a writer ignores them, the fleet marker is the last
     stop.

Safety
------
TWO-direction operation:
  --pause  set fleet pause marker (requires --yes)
  --resume clear marker (requires --yes)
  --status query current state (default action; no gate)

Marker location: data/fleet_emergency_pause.json with
{paused: bool, paused_at: ts, paused_by: str, reason: str}.

Atomic mkstemp+os.replace persistence pattern (same as
W963-16/22 tracking).

CLI:
  shopai fleet-emergency             -- status query (no gate)
  shopai fleet-emergency --pause --yes --reason "X"
  shopai fleet-emergency --resume --yes
  shopai fleet-emergency --json
"""
from .flow import FleetEmergencyPauseEngine

__all__ = ["FleetEmergencyPauseEngine"]
