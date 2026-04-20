# nav: modules

Domain-specific policy modules — risk, crisis, legal,
planning, federation, compliance, fulfillment, SEO.

## Physical source

- `core/risk/tripwire.py` — daily spend + ROAS floor
  tripwires (L7).
- `core/crisis/response.py` — LX.4 kill switch + incident
  ledger.
- `core/legal/` — policy/T&C compliance checks.
- `core/planning/` — L4 quarterly planner.
- `core/federation/` — LX.5 multi-store rule sharing.
- `execution/compliance/eu_ai_act_gate.py` — Article 50
  C2PA + disclosure gate (A1).
- `execution/fulfillment/`
  - `landed_cost.py` — de-minimis-aware COGS (A2).
  - `auto_fulfill.py` — CJ / Autods fulfilment dispatch.
- `execution/seo/`
  - `schema_stack.py` — JSON-LD @graph builder (A3).
  - `llms_txt.py` — llms.txt + markdown mirrors.
  - `seo_skill.py` — legacy keyword + backlink checks.

## Facade

`modules/__init__.py` re-exports the stable surface for
risk / crisis / landed_cost / EU gate / schema stack.

## CLI

```
python cli.py risk status
python cli.py crisis halt --reason "storm"
python cli.py landed-cost --fob 10 --destination US --origin CN
```

## Rules

- Each module is a *policy* — deterministic, no LLM.
- Add regression tests in `tests/` with the module name
  (`test_risk_tripwire.py`, `test_landed_cost.py`).
- Side effects only via the relevant adapter; never
  import requests directly inside these modules.
