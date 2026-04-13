---
title: "Adapter Hooks Shipped"
tags: [win, hooks, cycle, adapters]
created: "2026-04-13"
date: "2026-04-13"
impact: "high"
related:
  - "[[Adapter Hooks]]"
  - "[[Controller Loop]]"
  - "[[30 Adapters Milestone]]"
  - "[[Best-Effort Adapter Hooks]]"
---

# Adapter Hooks Shipped

## What happened

`core/autonomous/adapter_hooks.py` landed. The autonomous cycle
now actively uses the Wave-4 adapter ecosystem instead of just
bootstrapping it. Four hooks run at the tail of every tick:

1. **Analytics** — fires `shopai_cycle_complete` + `order_placed`
   events to PostHog / Mixpanel
2. **CRM** — upserts unique-email customers into HubSpot
3. **Helpdesk** — opens a Zendesk / Crisp / Intercom ticket when
   errors cross `SHOPAI_HELPDESK_ERROR_THRESHOLD`
4. **Automation** — POSTs a cycle summary to n8n / Zapier

## Why it's a win

- Operators opt in **by setting the API key only** — no config
  flag, no controller re-deploy
- Kill-switch via `SHOPAI_ADAPTER_HOOKS=off` for paranoid ops
- Each hook is [[Best-Effort Adapter Hooks|best-effort]]; none
  can break the cycle
- 17 new tests added (`tests/test_adapter_hooks.py`), all pass

## Bonus

Obsidian export expanded: the controller now writes a per-cycle
Decision note to `vault/Decisions/YYYY-MM-DD - {action}.md`
alongside the existing Win/Error notes. Deduplicated per action per day.

## Related

- [[Adapter Hooks]]
- [[Best-Effort Adapter Hooks]]
- [[Controller Loop]]
- [[30 Adapters Milestone]]
