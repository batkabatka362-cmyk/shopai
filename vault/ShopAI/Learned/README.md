---
title: "Learned — README"
tags: [readme, learned, auto]
created: "2026-04-13"
related:
  - "[[00 Home]]"
  - "[[Reflection Hook]]"
  - "[[Memory]]"
---

# Learned — README

> **This folder is written by ShopAI, not by you.**
>
> After every autonomous cycle the [[Reflection Hook]] mines
> repeated patterns and, once they cross the confidence threshold,
> promotes them to memory. Promoted patterns are auto-exported
> here via `VaultMemoryBridge.export_knowledge()` so you can see
> what the system has actually learned.

## Conventions

- Filenames are the pattern title, sanitised
- Frontmatter always carries `source: "shopai"` and `exported_at`
  (ISO-8601), plus an optional `confidence` float
- Re-running the exporter skips files that already exist — it
  never overwrites your edits

## Graph colour

Notes in this folder show up **orange** in the graph (see
[[Graph View Tips]]). A growing orange cluster means ShopAI is
learning.

## Gitignore

The folder itself is gitignored — your operator's learned state
is yours, not the repo's. This README is the single exception
(so fresh clones still explain the folder's purpose).

## Related

- [[Reflection Hook]] — how patterns get promoted
- [[Memory]] — where they live before export
- [[Graph View Tips]]
- [[00 Home]]
