# nav: tools

Scripts, utilities, and operational helpers.

## Physical source

- `tools/` — reusable CLI utilities.
- `scripts/` — daemon launchers + one-shot jobs.

## Key scripts

- `scripts/start_shopai.py` — daemon + API + dashboard
  full stack.
- `scripts/run_daemon.py` — autonomous loop only.
- `scripts/autopilot_loop.py` — 24/7 winner publish
  cycle (wrapped by run_daemon).
- `scripts/owner_loop.py` — Telegram poll + digest push.
- `scripts/shopai-*.service` — systemd units.

## Tools

- `tools/vault_sweep.py` — Obsidian note import.
- `tools/backfill_rules.py` — replay historical events
  into the learning pipeline.
- `tools/export_metrics.py` — CSV dump for analysis.

## Rules

- Scripts that run continuously live in `scripts/`.
- Scripts that run once and exit live in `tools/`.
- Both may be invoked via `python cli.py <name>` for
  discoverability, but the source stays here.
- systemd units have matching .service files so
  `systemctl enable shopai-<name>` just works.
