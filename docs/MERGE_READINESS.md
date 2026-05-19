# Merge Readiness Report — 2026-05-20

27 open PRs in this session. CI green on 23 of 24 with
results; the other 4 (#399 MCP server, #398 cross-sell
rules, #393 + #387 stacked PRs) still pending CI.

## Recommended merge order

The dependency graph is shallow: only 2 PRs are stacked
(#387 + #393 on top of #385). Everything else targets
`main` independently.

### Wave 1 — Foundation (merge these first, no internal deps)

These are pure-additive new modules + a clean fix. Merge
order between them doesn't matter; they don't conflict.

| PR | Title | Reason to merge first |
|---|---|---|
| #380 | Fix placeholder `support@example.com` | Critical bug fix on policy + page generators. No conflicts. |
| #378 | Extend niche coverage to pets/fitness/jewelry/outdoor/baby | Adds 5 niches to 6 existing generators. Every downstream PR (homepage hero, theme palette, etc.) assumes these niches exist. |
| #385 | Niche tag library | Unblocks #387 + #393 stacked PRs. |

### Wave 2 — Standalone niche modules (parallel-safe)

Each adds a new module under `engines/store_setup/`.
Zero conflicts between them. Can merge in any order.

  #379  Homepage hero
  #381  Theme palette recommender
  #382  Customer support KB
  #383  Welcome + abandoned-cart emails
  #384  Blog starter (3 SEO drafts)
  #386  Coupon playbook (6 evergreens)
  #388  Schema.org JSON-LD structured data
  #389  Customer segments starter pack
  #390  Loyalty tier templates
  #391  Announcement bar content
  #392  Metaobject definition starter
  #394  Review request email
  #395  Win-back email sequence
  #396  Homepage section ordering
  #397  Newsletter signup popup
  #398  Cross-sell rule templates

### Wave 3 — Stacked PRs (after #385 merges)

  #387  Auto-tagger niche-aware wiring (stacked on #385)
  #393  Smart collection rules (stacked on #385)

GitHub will auto-rebase these onto main when #385 lands.

### Wave 4 — Orchestrator + audit + CLI

These four PRs form the integration layer that lets the
operator drive everything via `shopai store launch` and
`shopai store audit`. Merge order:

  #376  Orchestrator-v2 (fan out to 7 appliers)
  #377  Launch audit extension (brand + descriptions + SEO)
  #374  `shopai store audit` CLI
  #375  `shopai store launch` CLI

After this wave, the CLI command runs the full chain.

### Wave 5 — MCP server (last)

  #399  MCP server skeleton -- exposes ShopAI to Claude

Doesn't strictly require the others to merge first;
the server registers the on-main tools and gracefully
handles missing engine modules. But shipping it AFTER
the niche modules means Day 1 users get the full
tool surface, not a placeholder set.

## After everything merges

  * `shopai store launch --niche beauty` walks the full
    chain end to end.
  * `shopai store audit` returns 8-check readiness.
  * Claude Desktop users `pip install mcp` + add the
    ShopAI server -> can call `recommend_full_launch_pack`
    from Claude conversations.
  * 24+ niche-aware modules consumable from CLI, engine,
    or MCP.

## Older PRs not in this session

  * #102 (FAILURE) -- 12 missing dispatchers fix; pre-
    session; investigate separately.
  * #101 (FAILURE) -- shopai suggest inline notes; pre-
    session.
  * #21 (SUCCESS) -- old CLAUDE.md PR.
