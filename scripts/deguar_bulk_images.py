"""Bulk image uploader for Shopify products — URL-driven.

The cached audit shows 21/21 Deguar products have only ONE image
each. E-commerce research: 3-4 images/product lifts CVR 30-50%
over single-image listings. Getting there by hand = 21 × 3 = 63
manual uploads. Getting there with this script = 10 min.

Workflow:

    1. Owner curates a config file mapping product *handles* to
       lists of image URLs. AliExpress supplier galleries work;
       unsplash / pexels lifestyle shots work; anything that's
       publicly reachable via https works.

       {
         "galaxy-star-projector-night-light": [
           "https://ae01.alicdn.com/kf/abc.jpg",
           "https://images.unsplash.com/photo-bedroom.jpg"
         ],
         "crystal-aromatherapy-oil-diffuser": [...]
       }

    2. Run:

       PYTHONPATH=. python scripts/deguar_bulk_images.py \\
           --config images.json --min-images 3 --dry-run

    3. If dry-run looks right, drop ``--dry-run``.

The script:
  * Fetches every active + draft product from Shopify.
  * Skips products already at ``--min-images`` or more.
  * For each queued URL, POSTs to ``/products/{id}/images.json``
    with ``{"image":{"src":"...","alt":"Product Title — N"}}``.
  * Retries 429 / 502 / 503 with exponential backoff.
  * Idempotency: skips URLs the product already has (Shopify
    returns the full image src, which we compare).

Safe to re-run. Read-plus-targeted-write. No existing images get
deleted — only NEW images appended.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


def _api(
    method: str, path: str, body: dict | None = None,
    *, url: str, token: str, retries: int = 4,
) -> dict:
    full = f"https://{url}/admin/api/2024-10/{path}"
    data = json.dumps(body).encode() if body is not None else None
    headers = {
        "X-Shopify-Access-Token": token,
        "Accept": "application/json",
        "User-Agent": "ShopAI/bulk-images",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"

    last_exc: Exception | None = None
    for i in range(retries):
        try:
            req = urllib.request.Request(
                full, data=data, headers=headers, method=method,
            )
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            last_exc = e
            if e.code in (429, 502, 503) and i < retries - 1:
                wait = 2 ** (i + 1)
                sys.stderr.write(
                    f"  {e.code} on {path} — retry in {wait}s\n",
                )
                time.sleep(wait)
                continue
            raise
        except urllib.error.URLError as e:
            last_exc = e
            if i < retries - 1:
                wait = 2 ** (i + 1)
                sys.stderr.write(f"  net err — retry in {wait}s\n")
                time.sleep(wait)
                continue
            raise
    if last_exc:
        raise last_exc
    raise RuntimeError("retries exhausted")


def _fetch_all_products(*, url: str, token: str) -> list[dict]:
    products: list[dict] = []
    resp = _api(
        "GET",
        "products.json?limit=250&fields=id,title,handle,status,images",
        url=url, token=token,
    )
    products = resp.get("products") or []
    return products


def _upload(
    product_id: str, src: str, alt: str,
    *, url: str, token: str,
) -> dict:
    return _api(
        "POST", f"products/{product_id}/images.json",
        {"image": {"src": src, "alt": alt}},
        url=url, token=token,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--config", required=True,
        help=(
            "Path to JSON mapping {handle: [url, url, ...]}."
        ),
    )
    ap.add_argument(
        "--min-images", type=int, default=3,
        help=(
            "Skip products that already have this many "
            "or more images (default: 3)."
        ),
    )
    ap.add_argument(
        "--dry-run", action="store_true",
        help=(
            "Print what would happen but don't POST."
        ),
    )
    ap.add_argument(
        "--limit", type=int, default=0,
        help=(
            "Max products to update (0 = all). "
            "Good for piloting on one product first."
        ),
    )
    ap.add_argument(
        "--only", default="",
        help=(
            "Only process this product handle "
            "(single-target pilot)."
        ),
    )
    args = ap.parse_args(argv)

    url = os.environ.get("SHOPAI_SHOPIFY_URL") or ""
    token = (
        os.environ.get("SHOPAI_SHOPIFY_KEY")
        or os.environ.get("SHOPAI_SHOPIFY_TOKEN")
        or ""
    )
    if not url or not token:
        print(
            "ERR: set SHOPAI_SHOPIFY_URL + SHOPAI_SHOPIFY_KEY",
            file=sys.stderr,
        )
        return 2

    try:
        with open(args.config, encoding="utf-8") as fh:
            plan: dict[str, list[str]] = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERR: cannot read config: {exc}", file=sys.stderr)
        return 2

    if not isinstance(plan, dict):
        print(
            "ERR: config must be a JSON object of "
            "{handle: [url, ...]}",
            file=sys.stderr,
        )
        return 2

    # Filter planned handles
    if args.only:
        plan = {k: v for k, v in plan.items() if k == args.only}
        if not plan:
            print(
                f"ERR: --only {args.only} not in config",
                file=sys.stderr,
            )
            return 2

    print(f"Store: {url}")
    print(f"Config: {args.config} "
          f"({len(plan)} handles planned)")
    if args.dry_run:
        print("Mode: DRY-RUN")
    print()

    products = _fetch_all_products(url=url, token=token)
    by_handle = {p["handle"]: p for p in products}

    # Precompute summary
    totals = {"skip_has_enough": 0, "skip_not_found": 0,
              "queued": 0, "uploaded": 0, "errors": 0,
              "skip_duplicate_src": 0}
    updates = 0

    for handle, urls in plan.items():
        if args.limit and updates >= args.limit:
            break
        p = by_handle.get(handle)
        if p is None:
            print(f"⚠ {handle}: product not found in store")
            totals["skip_not_found"] += 1
            continue
        current = p.get("images") or []
        current_count = len(current)
        if current_count >= args.min_images:
            print(f"✓ {handle}: already has {current_count} "
                  f"images — skipping (min={args.min_images})")
            totals["skip_has_enough"] += 1
            continue
        need = args.min_images - current_count
        queue = list(urls)[:need]
        totals["queued"] += len(queue)

        pid = str(p["id"])
        title = p.get("title", "")
        existing_srcs = {
            (img.get("src") or "")
            for img in current if isinstance(img, dict)
        }

        print(f"→ {handle} (id {pid}): "
              f"{current_count}/{args.min_images} images, "
              f"uploading {len(queue)}")

        for idx, src in enumerate(queue, start=current_count + 1):
            if src in existing_srcs:
                print(f"    · {src[:70]} — already attached, skip")
                totals["skip_duplicate_src"] += 1
                continue
            alt = f"{title} — image {idx}"
            if args.dry_run:
                print(f"    [dry] POST image {idx}: {src[:70]}")
                continue
            try:
                res = _upload(
                    pid, src, alt, url=url, token=token,
                )
                if res.get("image"):
                    print(f"    ✓ uploaded #{idx}: "
                          f"{src[:60]}")
                    totals["uploaded"] += 1
                    # Throttle: 2 cps Shopify limit
                    time.sleep(0.5)
                else:
                    print(f"    ✗ upload #{idx} empty response: "
                          f"{src[:60]}")
                    totals["errors"] += 1
            except Exception as exc:  # noqa: BLE001
                print(f"    ✗ upload #{idx} failed: {exc}")
                totals["errors"] += 1
        updates += 1

    print()
    print("═══ Summary ═══")
    for k, v in totals.items():
        print(f"  {k:22s}: {v}")
    if args.dry_run:
        print("\n  (DRY-RUN — no actual writes. "
              "Re-run without --dry-run when ready.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
