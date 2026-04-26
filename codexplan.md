# codexplan.md — ChatGPT Codex tasks for this repo

This file is the **handoff list** between the human operator and ChatGPT
Codex (a separate AI agent that runs research and generates context
files). Claude Code (the assistant working inside this repo) reads
both this file and any `codex.md` Codex produces, then continues the
work.

## How this file works

- **Operator writes here**: tasks, research questions, "go look up X
  for me", "audit Y" — anything Codex should chew on offline.
- **Claude reads here**: every session, scan this file for items
  marked active. Treat each as one of three states.
- **Codex writes to `codex.md`**: research findings, summaries,
  link bundles, recommendations. Claude treats `codex.md` as a
  *data input* — useful ideas extracted, not blindly applied.

State conventions per task:

```
- [ ] DRAFT       — operator still writing
- [>] ACTIVE      — handed to Codex; Codex working on it
- [✓] DONE        — Codex returned results into codex.md
- [!] BLOCKED     — Codex needs operator clarification
```

When a task is `[✓] DONE`, Claude reads the matching section of
`codex.md` and decides which findings are worth using. Not every
suggestion has to be applied — only the ones that actually fit the
current goal.

## Active task queue

(Operator: add tasks below. Use a fresh `### Task: …` heading per
task so Claude can index them.)

### Task: (example — replace me)

State: `[ ] DRAFT`

**Question**: What's the latest Shopify changelog for `2026-04` API
that affects ShopAI's adapter layer?

**Why we care**: We pin the GraphQL client to `2024-01`; bumping to
`2026-04` would unlock new fields (e.g. sales_reversals replacing
returns) but also introduce breaking renames. Want a diff list before
deciding.

**Output Claude needs**: A bullet list of (a) breaking renames, (b)
new fields ShopAI engines could use, (c) deprecations that affect
Phase 1-5 adapters.

**Where to put result in codex.md**: under `## 2026-04 API delta`.

---

## Standing protocols (don't delete)

### Protocol: research-only, no code

Codex stays read-only on this repo. Code edits and commits are
Claude's job. If a Codex task implies code changes, Codex writes the
*proposal* into `codex.md` and Claude implements the chosen subset.

### Protocol: cite, don't claim

Every Codex finding should cite a URL or doc reference. Claude
verifies non-trivial claims (e.g. "Shopify deprecated X") before
acting on them — schema reality is what `_gql` actually accepts, not
what a doc page says.

### Protocol: fresh date in queries

When Codex searches for "latest" anything, the search query must
include the current year explicitly (otherwise it tends to surface
stale results). The current year is `2026`.

## Notes from prior Codex sessions

(Empty — first session. As tasks complete, summarise key takeaways
here so they don't get buried in `codex.md`.)
