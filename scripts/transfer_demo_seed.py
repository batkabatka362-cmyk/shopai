"""Seed synthetic per-store actions to demo cross-store transfer.

The ``shopai transfer suggest`` command (PR #242) requires
actions tagged with ``store_id`` to recommend transfers. The
autonomous loop (PR #244) tags every action it runs, but on a
fresh install the queue is empty, so transfer-suggest returns
"no candidates" even after a successful autonomous run.

This script seeds N synthetic EXECUTED actions on a source
store with positive outcomes, so an operator can validate the
end-to-end flow without waiting for real engine activity to
accumulate.

Usage:
    python scripts/transfer_demo_seed.py --from store-a --to store-b
    python -m cli transfer suggest --from store-a --to store-b

Safety:
- Writes directly to the production approval queue. Run only on
  dev / staging.
- Each seeded row is action_type-prefixed with ``DEMO_`` so
  operators can grep + remove via SQL if needed.
- Use ``--clean`` to wipe rows from a prior demo run before
  seeding fresh.

This is a STANDALONE script (under scripts/), not a CLI
subcommand on the user-facing surface, because seeding the
production queue is a destructive-adjacent action that deserves
an explicit script-level opt-in rather than living next to
read-only commands.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

# Allow running as ``python scripts/transfer_demo_seed.py`` from
# the repo root: prepend the project root so ``core.approval``
# resolves without requiring an editable install.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# Synthetic action templates. Each (engine, action_type, capability,
# params) gets seeded onto the source store. Designed so different
# engines look different in the transfer-suggest output.
_TEMPLATES = [
    (
        "loyalty", "DEMO_mint_loyalty_code",
        "SHOPIFY_CREATE_DISCOUNT",
        {"customer_id": "gid://shopify/Customer/demo-1",
         "percentage": 10, "ttl_days": 30},
    ),
    (
        "cart_recovery", "DEMO_mint_cart_recovery_code",
        "SHOPIFY_CREATE_DISCOUNT",
        {"token": "DEMO-1", "value": 15, "value_kind": "percentage",
         "ttl_days": 7},
    ),
    (
        "discount_strategy", "DEMO_mint_strategy_code",
        "SHOPIFY_CREATE_DISCOUNT",
        {"audience": "all", "percentage": 20, "ttl_days": 14},
    ),
    (
        "email_marketing", "DEMO_mint_campaign_code",
        "SHOPIFY_CREATE_DISCOUNT",
        {"goal": "winter sale", "value": 25,
         "value_kind": "percentage", "ttl_days": 30},
    ),
]


def _seed(from_store: str, to_store: str, n: int, clean: bool) -> int:
    from core.approval.queue import (
        ApprovalStatus, get_approval_queue,
    )

    queue = get_approval_queue()

    if clean:
        deleted = _clean_demo_rows(queue, [from_store, to_store])
        print(f"Cleaned {deleted} DEMO row(s) from prior runs.")

    print(
        f"Seeding {n} executed action(s) per template on "
        f"{from_store!r} ({len(_TEMPLATES)} templates)..."
    )
    seeded_ids: list[str] = []
    for engine, action_type, capability, params in _TEMPLATES:
        for i in range(n):
            # Enqueue, then transition straight to EXECUTED via
            # internal UPDATE. The queue's normal lifecycle would
            # require approve+execute; for the demo we shortcut.
            action = queue.enqueue(
                engine=engine,
                action_type=action_type,
                capability=capability,
                params={**params, "demo_seq": i},
                narrative=f"DEMO seed for {engine}/{action_type}",
                store_id=from_store,
            )
            with queue._conn:
                queue._conn.execute(
                    "UPDATE pending_actions SET status=?, "
                    "decided_at=?, decided_by=? WHERE id=?",
                    (
                        ApprovalStatus.EXECUTED.value,
                        time.time(), "demo_seed", action.id,
                    ),
                )
            # Attach a positive outcome so transfer-suggest's
            # ranking has revenue / polarity signal.
            try:
                queue.record_outcome(
                    action.id,
                    topic="orders/create",
                    polarity="positive",
                    metrics={"revenue": 50.0 * (i + 1)},
                    source_event="demo_seed",
                )
            except Exception as exc:  # noqa: BLE001
                print(f"  warning: outcome attach failed: {exc}")
            seeded_ids.append(action.id)

    print(f"\nSeeded {len(seeded_ids)} action(s).")
    print()
    print("Verify with:")
    print(
        f"  python -m cli transfer suggest "
        f"--from {from_store} --to {to_store}"
    )
    print()
    print(
        "To clean up afterwards, re-run with --clean (or use "
        "--clean alone to wipe without re-seeding)."
    )
    return 0


def _clean_demo_rows(queue, store_ids: list[str]) -> int:
    """Delete DEMO_-prefixed rows from the queue + their
    outcomes for the named stores."""
    deleted_total = 0
    with queue._conn:
        for sid in store_ids:
            # Collect ids first so we can wipe outcomes too.
            ids = [
                r["id"] for r in queue._conn.execute(
                    "SELECT id FROM pending_actions "
                    "WHERE store_id = ? AND action_type LIKE 'DEMO_%'",
                    (sid,),
                ).fetchall()
            ]
            if not ids:
                continue
            placeholders = ",".join("?" * len(ids))
            queue._conn.execute(
                f"DELETE FROM action_outcomes "
                f"WHERE action_id IN ({placeholders})",
                ids,
            )
            queue._conn.execute(
                f"DELETE FROM pending_actions "
                f"WHERE id IN ({placeholders})",
                ids,
            )
            deleted_total += len(ids)
    return deleted_total


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Seed synthetic per-store actions to demo "
            "shopai transfer suggest."
        ),
    )
    parser.add_argument(
        "--from", required=True, dest="from_store",
        help="Source store ID (the one that gets the success data)",
    )
    parser.add_argument(
        "--to", required=True, dest="to_store",
        help=(
            "Target store ID. Used for the cleanup wipe + "
            "shown in the verify suggestion line."
        ),
    )
    parser.add_argument(
        "-n", "--n", type=int, default=3,
        help="Number of executed rows per template (default: 3).",
    )
    parser.add_argument(
        "--clean", action="store_true",
        help=(
            "Wipe DEMO_-prefixed rows from prior runs before "
            "seeding. Use ``--clean --n 0`` to wipe without "
            "re-seeding."
        ),
    )

    args = parser.parse_args()

    if args.from_store == args.to_store:
        print(
            "Error: --from and --to must be different stores "
            "(otherwise the transfer-suggest filter excludes "
            "every seeded row).",
            file=sys.stderr,
        )
        return 1

    return _seed(
        from_store=args.from_store,
        to_store=args.to_store,
        n=max(0, int(args.n)),
        clean=args.clean,
    )


if __name__ == "__main__":
    sys.exit(main())
