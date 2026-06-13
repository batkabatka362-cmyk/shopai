"""Plan Executor Engine — W963-36.

Executes a plan composed by W963-31 plan_composer as a single
batched submission to the approval queue. Instead of:

  shopai earn-bootstrap ...
  shopai store configure ...
  shopai blog-candidates ...
  shopai ads connect ...
  shopai cycle schedule

The operator runs:

  shopai plan-execute "cold_start" --store X --yes

And the system enqueues 5 PENDING actions tagged with the same
plan_id. Operator can:
  - approve the whole batch at once
  - approve step-by-step with `shopai approvals pending`
  - reject the plan to undo

Bible scoring:
  Q1 (20-store leverage): the same plan template can fan
     across stores via fleet_autopilot composition. At 20
     stores, "fire cold_start on all" becomes ONE command.
  Q2 (substrate composability): pure synthesis — composes
     plan_composer + ApprovalQueue.enqueue + active_store.

Safety
------
Triple-gated:
  - default dry-run
  - --yes flag required to enqueue
  - SHOPAI_PLAN_EXECUTOR_ENABLED=1 env required
  - max-steps cap

CLI:
  shopai plan-execute "cold_start"                  -- dry-run
  shopai plan-execute "cold_start" --yes            -- live
  shopai plan-execute "X" --store STORE --yes
  shopai plan-execute "X" --max-steps 3 --json
"""
from .flow import PlanExecutorEngine

__all__ = ["PlanExecutorEngine"]
