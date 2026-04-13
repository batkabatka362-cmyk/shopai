---
title: "00 Home"
tags: [moc, index, home]
created: "2026-04-13"
aliases: ["Home", "Index", "MOC"]
related:
  - "[[ShopAI Architecture]]"
  - "[[_Concepts MOC]]"
  - "[[_Adapters Catalog]]"
  - "[[_Capabilities MOC]]"
---

# 00 Home

> **Map of content for the ShopAI vault.** Start here. Every subsystem,
> every adapter, every decision eventually threads back to this node in
> the graph.

## Navigate

| Area | Entry point |
|------|-------------|
| **System overview** | [[ShopAI Architecture]] |
| **All concepts** | [[_Concepts MOC]] |
| **All adapters** | [[_Adapters Catalog]] |
| **All capabilities** | [[_Capabilities MOC]] |

## Core systems

- [[Brain]] — decision + learning
- [[Memory]] — unified memory + vault bridge
- [[Controller Loop]] — autonomous cycle phases
- [[Capability Routing]] — how the smart router picks an adapter
- [[Reflection Hook]] — post-cycle pattern mining
- [[Adapter Hooks]] — per-cycle side effects (analytics, CRM, helpdesk, automation)

## Knowledge

- [[Shopify API Basics]]
- [[Obsidian Integration]]
- [[HTTP Auth Patterns]]
- [[YAML Frontmatter]]
- [[Pytest Patterns]]
- [[Graph View Tips]]

## Decisions (ADRs)

- [[Use Obsidian for Memory]]
- [[Use HubSpot for CRM]]
- [[Why Smart Router]]
- [[Use n8n over Zapier]]
- [[Best-Effort Adapter Hooks]]

## Wins

- [[Obsidian Integration Complete]]
- [[30 Adapters Milestone]]
- [[Adapter Hooks Shipped]]

## Auto-written (by ShopAI)

- `Wins/` — successful cycle summaries
- `Errors/` — degraded-cycle reports
- `Decisions/YYYY-MM-DD - {action}.md` — per-cycle top action
- `ShopAI/Learned/` — promoted patterns from the reflection loop

## The principle

> Don't build new features. Find working apps/tools/AIs and connect
> them to ShopAI.

The **core** decides; the **adapters** execute. No business logic
lives in the core — all behaviour is learned, not programmed.
