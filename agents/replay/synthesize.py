"""Synthetic Shopify order payload generator.

Why this exists (PATH_TO_T2.md §2 P0-B extension):
``shopai replay-orders`` feeds a JSONL file of Shopify order
payloads through the live webhook pipeline — but the owner
needs a JSONL file first. Exporting real orders from a live
store requires T1 already running. For the T0 → T1 bridge
(validate the learning loop fires correctly before any live
deploy) we need owner-runnable synthetic orders.

This module generates deterministic Shopify-shaped order
dicts. Seeded random so replays are reproducible. Each
payload carries:

  * ``id`` / ``order_id``
  * ``total_price`` drawn from a configurable revenue
    distribution
  * ``line_items`` with a synthetic SKU + quantity
  * ``note_attributes`` including a ``shopai_decision_id`` in
    the configured ``decision_ids`` pool so the webhook can
    back-fill a Deliberation observation
  * ``customer``, ``financial_status=paid``, ``currency=USD``

CLI usage (replay CLI wires ``--synthesize N``):

    $ shopai replay-orders /dev/null --synthesize 100

Programmatic:

    >>> from agents.replay.synthesize import synthesize_orders
    >>> orders = synthesize_orders(
    ...     count=10, decision_ids=["dec_abc"],
    ... )

Pure stdlib. Deterministic under a seed.
"""
from __future__ import annotations

import random
import uuid
from typing import Any


_DEFAULT_PRICE_BANDS = (
    # (weight, low, high)
    (3, 9.99, 19.99),    # small-ticket impulse
    (5, 19.99, 49.99),   # core AOV band
    (2, 49.99, 149.99),  # premium
    (1, 149.99, 399.99), # high-ticket
)


def _pick_band(rng: random.Random) -> tuple[float, float]:
    total = sum(w for w, *_ in _DEFAULT_PRICE_BANDS)
    roll = rng.uniform(0, total)
    acc = 0.0
    for w, lo, hi in _DEFAULT_PRICE_BANDS:
        acc += w
        if roll <= acc:
            return lo, hi
    return _DEFAULT_PRICE_BANDS[0][1:]


def synthesize_order(
    *,
    index: int,
    rng: random.Random,
    decision_id: str | None = None,
) -> dict[str, Any]:
    """Return one Shopify-shaped order dict.

    ``index`` is used to derive a stable ``id``; ``rng`` drives
    revenue + quantity variation. ``decision_id`` (optional)
    is written into ``note_attributes`` so the webhook can
    back-fill the matching Deliberation.
    """
    lo, hi = _pick_band(rng)
    price = round(rng.uniform(lo, hi), 2)
    qty = rng.choice([1, 1, 1, 2, 2, 3])
    subtotal = round(price * qty, 2)
    # Modest shipping flat fee so `total_price` varies
    shipping = rng.choice([0.0, 3.99, 5.99, 0.0])
    total = round(subtotal + shipping, 2)
    oid = f"synth-ord-{index:06d}"
    sku = f"SYNTH-SKU-{rng.randint(1, 50):04d}"
    payload: dict[str, Any] = {
        "id": oid,
        "order_id": oid,
        "name": f"#SYN{index:06d}",
        "financial_status": "paid",
        "currency": "USD",
        "total_price": f"{total:.2f}",
        "subtotal_price": f"{subtotal:.2f}",
        "total_shipping_price_set": {
            "shop_money": {
                "amount": f"{shipping:.2f}",
                "currency_code": "USD",
            },
        },
        "line_items": [
            {
                "id": rng.randint(10**9, 10**10),
                "sku": sku,
                "title": f"Synthetic Widget {sku[-4:]}",
                "quantity": qty,
                "price": f"{price:.2f}",
                "product_id": rng.randint(10**9, 10**10),
                "variant_id": rng.randint(10**9, 10**10),
            },
        ],
        "customer": {
            "id": rng.randint(10**9, 10**10),
            "email": f"synth_{index}@example.test",
            "first_name": "Synth",
            "last_name": f"Shopper{index}",
        },
        "note_attributes": [],
    }
    if decision_id:
        payload["note_attributes"].append({
            "name": "shopai_decision_id",
            "value": str(decision_id),
        })
    return payload


def synthesize_orders(
    *,
    count: int,
    seed: int = 42,
    decision_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Deterministic batch generator.

    ``decision_ids`` is a pool — if supplied, each order
    rotates through the pool so the webhook back-fill exercises
    the Deliberation ledger. Empty pool → no decision_id
    attribute (simulates organic-search orders).
    """
    if count <= 0:
        raise ValueError("count must be > 0")
    rng = random.Random(int(seed))
    pool = list(decision_ids or [])
    orders: list[dict[str, Any]] = []
    for i in range(int(count)):
        did = pool[i % len(pool)] if pool else None
        orders.append(synthesize_order(
            index=i + 1, rng=rng, decision_id=did,
        ))
    return orders


def synthesize_orders_with_random_decisions(
    *,
    count: int,
    seed: int = 42,
    attach_rate: float = 0.6,
) -> list[dict[str, Any]]:
    """Batch generator that mints a random decision_id on
    ``attach_rate`` of orders (the rest stay organic).

    Useful when the owner doesn't have recorded decisions yet
    — the webhook will still record an outcome even though the
    decision_id won't match any real Deliberation.
    """
    if not 0.0 <= attach_rate <= 1.0:
        raise ValueError("attach_rate must be in [0, 1]")
    rng = random.Random(int(seed))
    orders: list[dict[str, Any]] = []
    for i in range(int(count)):
        did = None
        if rng.random() < attach_rate:
            did = f"dec_synth_{uuid.UUID(int=rng.getrandbits(128)).hex[:12]}"
        orders.append(synthesize_order(
            index=i + 1, rng=rng, decision_id=did,
        ))
    return orders
