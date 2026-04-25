# scripts/ — daemons and one-shot utilities

Two kinds of files live here, logically split below. We
keep them in one folder because 16 external references
(systemd units, docker-entrypoint.sh, docs, cli.py) point
at `scripts/*` — a physical split would require coordinated
deployment churn with zero capability upside.

## Daemons (long-running)

Launched via systemd / docker / `python scripts/<name>.py`.
They run indefinitely unless stopped.

- `start_shopai.py` — full stack bootstrapper: daemon +
  API + dashboard.
- `run_daemon.py` — autonomous cycle loop only.
- `autopilot_loop.py` — 24/7 winner → publish → activate
  cycle (wrapped by `run_daemon.py`).
- `owner_loop.py` — Telegram poll + digest push.

### systemd units

- `shopai-daemon.service` — enables `run_daemon.py` as a
  service.
- `shopai-api.service` — enables the HTTP API.

## One-shot utilities

Invoke from the shell or `cli.py`; they exit when done.

- `add_store.py` — register a new Shopify store.
- `advanced_store_setup.py` — idempotent full-store
  configuration (collections, discounts, emails).
- `add_cross_sell.py` — add cross-sell rules to a store.
- `optimize_store.py` — run SEO + content optimisations.
- `publish_content.py` — push a single content piece
  (blog / page / email).

## Rules

- New daemon → add matching `shopai-<name>.service`
  systemd unit in the same folder.
- New one-shot → invoke via `cli.py` for discoverability;
  keep the source here.
- Do not put reusable helpers here. Those go in `utils/`
  or `tools/`.

## Planned future split

If the folder ever exceeds ~20 files we can split
`daemons/` + `utils/` at that point. Until then, this
README is the conceptual boundary — not physical
subfolders. (See docs/REPO_STRUCTURE_AUDIT.md cleanup
item 3 for the deferred physical split.)
