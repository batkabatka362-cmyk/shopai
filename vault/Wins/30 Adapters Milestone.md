---
title: "30 Adapters Milestone"
tags: [win, milestone, adapters]
created: "2026-04-13"
date: "2026-04-13"
impact: "high"
related:
  - "[[_Adapters Catalog]]"
  - "[[Adapter Pattern]]"
  - "[[Why Smart Router]]"
---

# 30 Adapters Milestone

## What happened

Wave 1 through Wave 4 landed a total of **30+ adapters** across
**17 categories**, every one of them routable via the
[[Capability Routing|smart router]]. See the complete list in
[[_Adapters Catalog]].

## Why it's a win

- **No vendor lock-in anywhere.** Every capability has at least
  one configured adapter; most have two or three.
- **Router-driven** — adding a new vendor stays a ~100-line change
  per [[Adapter Pattern]].
- **Self-healing** — flaky vendors demote themselves automatically
  via `ActionWeightStore`.

## Wave breakdown

| Wave | Shipped |
|------|---------|
| Wave 1 | Core LLMs + email + payment + search |
| Wave 2 | Playwright browser, Firecrawl scraper, voice, ads |
| Wave 3 | 8 new APIs across 6 groups |
| Wave 4 | Intelligence (Exa, SimilarWeb), analytics (PostHog, Mixpanel), helpdesk (Zendesk, Crisp), CRM (HubSpot), automation (n8n) |

## What it unlocks

- [[Adapter Hooks]] — analytics, CRM, helpdesk, automation side
  effects on every cycle
- Vendor experiments — the router makes A/B-ing providers trivial
- Cost routing — expensive reasoning to Anthropic, cheap to Groq

## Related

- [[_Adapters Catalog]]
- [[Adapter Pattern]]
- [[Why Smart Router]]
- [[Adapter Hooks Shipped]]
