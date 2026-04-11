#!/usr/bin/env python3
"""Add a new store to ShopAI — zero code needed.

Usage:
  python scripts/add_store.py --url mystore.myshopify.com --token shpat_xxx
  python scripts/add_store.py --url mystore.myshopify.com --token shpat_xxx --name "My Store" --niche home
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load env
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ[k] = v


def main():
    parser = argparse.ArgumentParser(description="Register a new Shopify store")
    parser.add_argument("--url", required=True, help="Store URL (e.g. mystore.myshopify.com)")
    parser.add_argument("--token", required=True, help="Shopify access token (shpat_xxx)")
    parser.add_argument("--name", default="", help="Store display name")
    parser.add_argument("--niche", default="", help="Store niche (home, fashion, tech, etc.)")
    parser.add_argument("--type", default="dropshipping", help="Store type")
    args = parser.parse_args()

    print()
    print("=" * 50)
    print("  ShopAI — New Store Registration")
    print("=" * 50)
    print()
    print("  URL:   {}".format(args.url))
    print("  Token: {}...".format(args.token[:15]))
    print("  Name:  {}".format(args.name or "(auto-detect)"))
    print("  Niche: {}".format(args.niche or "(general)"))
    print()

    from core.system.store_registry import get_store_registry
    registry = get_store_registry()

    print("[1/7] Validating credentials...")
    start = time.monotonic()
    result = registry.register(
        shop_url=args.url,
        token=args.token,
        name=args.name,
        niche=args.niche,
        store_type=args.type,
    )

    elapsed = time.monotonic() - start

    if result.get("status") == "error":
        print()
        print("  ERROR: {}".format(result.get("error", "Unknown")))
        print()
        return 1

    print()
    print("=" * 50)
    print("  STORE REGISTERED SUCCESSFULLY!")
    print("=" * 50)
    print()
    print("  Store ID: {}".format(result.get("store_id", "")))
    print("  Name:     {}".format(result.get("name", "")))
    print("  URL:      {}".format(result.get("shop_url", "")))
    print()

    # Show setup steps
    setup = result.get("setup", {})
    for step in setup.get("steps", []):
        for k, v in step.items():
            if k == "error":
                continue
            print("  {} {}".format(
                "OK" if v != "error" else "!!",
                "{}: {}".format(k, v)))

    print()
    print("  Total time: {:.1f}s".format(elapsed))
    print()
    print("  Store is now managed by ShopAI!")
    print("  Run daemon: python scripts/run_daemon.py")
    print("=" * 50)
    return 0


if __name__ == "__main__":
    sys.exit(main())
