# nav: agents

Narrow, single-purpose LLM agents. Each agent is a thin
planner wrapping a deterministic engine below.

## Physical source

`agents/` — one subfolder per agent.

- `owner_dialog/` — Telegram / terminal dialog with the
  owner. Parses goals, asks clarifying questions.
- `marketing/` — ad-copy + campaign planner.
- `learning/` — pattern promoter + decay (see nav_flow).
- `shopify/` — product-copy generator.
- `fulfillment/` — supplier-selection agent.
- `research/` — niche + trend discovery.

## Contract

Every agent exposes:
- `plan(goal: dict) -> list[Step]` — deterministic-first
  planner (LLM only for free-form text).
- `execute(step)` — delegates to the appropriate engine
  under `engines/`.
- `record_outcome(step_id, ok, revenue)` — closes the
  loop via `OutcomeRecorder`.

## Budget

Per CLAUDE.md §4b/C: per-cycle LLM cost ≤ $0.10. Agents
that burn more get escalation via insight_synthesizer.

## Rules

- No new agent without a corresponding test file in
  `tests/test_<agent>_agent.py`.
- No agent that writes to Shopify directly — route
  through `core/bridge/shopify_connector.py`.
- LLM call budget per agent is declared in
  `core/adapters/config.py` and enforced by the router.
