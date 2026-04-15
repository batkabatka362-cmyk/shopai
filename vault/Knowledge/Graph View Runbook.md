---
title: "Graph View Runbook"
tags: [runbook, operator, graph, obsidian, setup]
created: "2026-04-15"
related:
  - "[[Graph View Tips]]"
  - "[[Obsidian Integration]]"
  - "[[00 Home]]"
---

# Graph View Runbook

> Step-by-step for a first-time operator. Pair this with
> [[Graph View Tips]] once you know your way around.

## Desktop (recommended)

1. Install Obsidian from <https://obsidian.md/download>.
2. Launch → **Open folder as vault** → pick the repo's
   `vault/` directory (e.g. `~/shopai/vault`).
3. The vault opens with `00 Home.md` as the landing note.
4. `Ctrl` / `Cmd` + `G` → **Graph view** opens on the right.
5. Colour groups are already loaded from `.obsidian/graph.json`:
   - **Blue** — `Concepts/` (durable knowledge)
   - **Cyan** — `Knowledge/` (reference / how-to)
   - **Red** — `Errors/` (things that broke)
   - **Green** — `Wins/` (things that worked)
   - **Purple** — `Decisions/` (ADRs, auto-logged cycle decisions)
   - **Orange** — `ShopAI/Learned/` (auto-exported learnings)

## Mobile / web

Obsidian has iOS and Android apps. To sync the repo vault to a
phone:

- **Git-based:** clone the repo on the device, open `vault/` in
  Obsidian mobile. Operators comfortable with git get free
  history.
- **Obsidian Sync** (paid) — encrypted, conflict-free, no git.

## Verify ShopAI is populating the graph

```bash
OBSIDIAN_VAULT_PATH=./vault python -c "
from core.adapters.obsidian.memory_bridge import VaultMemoryBridge
from pathlib import Path
b = VaultMemoryBridge('./vault')
# Minimal memory shim — matches the ingest() contract.
class M:
    def __init__(self): self.calls = 0
    def ingest(self, **kw): self.calls += 1
m = M()
print(b.import_vault(m))
print('ingests:', m.calls)
"
```

A healthy vault prints `{'imported': N, 'skipped': 0, 'errors': 0}`
with `N >= 40` and matching `ingests`.

## First-cycle expectations

After one autonomous cycle with `OBSIDIAN_VAULT_PATH` set:

- `vault/Wins/` or `vault/Errors/` gets a new cycle note
- `vault/Decisions/` gets a new auto-logged decision (if the
  brain proposed an action)
- `vault/ShopAI/Learned/` grows whenever the [[Reflection Hook]]
  promotes a pattern OR once an hour on the sweep

Open the graph — the new cycle note should be a coloured node
with a wikilink edge back to `[[ShopAI Architecture]]`.

## Troubleshooting

- **Nothing shows up:** `OBSIDIAN_VAULT_PATH` not set, or vault
  path not a real directory. Check `get_config()`.
- **Graph is grey:** `.obsidian/graph.json` didn't load. Re-open
  the vault or check file syntax.
- **`Example Learned Pattern` and `How Auto-Export Works` missing:**
  `.gitignore` may have reset. Re-check the exception rules.

## Related

- [[Graph View Tips]]
- [[Obsidian Integration]]
- [[00 Home]]
