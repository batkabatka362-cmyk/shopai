"""Earn Path — W963-88 (operator on-ramp).

Smart "what's the exact next step?" guide for an operator
starting from scratch. Reads the current state across:

  - go-live check results (env-var coverage)
  - store niche assignments
  - cycle schedule installed
  - first cycle ran
  - first revenue
  - Phase 4 history populated
  - Phase 5 auto-disarm enabled

...and emits the SINGLE next-most-important command for
the operator to run. Like a wizard but stateless: every
time the operator runs `shopai earn-path`, it reflects
the current state of the empire.

Eight stages (linear progression):
  1. config_env       earn-config --apply
  2. notify_webhook   export SHOPAI_NOTIFY_WEBHOOK_URL=...
  3. set_niches       shopai niche --set <store> <niche>
  4. seed_catalog     shopai earn-bootstrap --niche X
  5. schedule_cron    shopai cycle schedule --recommend
  6. first_cycle      shopai cycle run --yes
  7. enable_phase5    export SHOPAI_AUTO_DISARM_ON_OVERRIDE=1
  8. earning          (complete -- monitor with shopai
                      morning-brief)

Each stage carries: title, status (done / next / pending),
exact CLI command, brief rationale. Operator sees only
"top next step" + condensed progress bar.

Pattern J + Pattern Q.

CLI:
  shopai earn-path
  shopai earn-path --json
"""
from .flow import EarnPathEngine

__all__ = ["EarnPathEngine"]
