"""End-to-end smoke test for the ShopAI MCP toolset.

Verifies the full chain works against a real Shopify dev
store:

  1. .env loads -- SHOPAI_SHOPIFY_URL + SHOPAI_SHOPIFY_KEY
     resolve.
  2. Shopify Admin API token is valid (cheap shop.json
     read).
  3. Engine layer imports cleanly.
  4. Each `recommend_*` MCP tool returns
     `{status: "ok", data}` -- generators work without
     touching Shopify.
  5. Read-only audit runs against the live store.
  6. (Optional, `--apply`) One safe write
     (`apply_announcement_bar`) goes through and
     creates the page.

Run:

  python scripts/smoke_test_shopai_mcp.py --niche beauty
  python scripts/smoke_test_shopai_mcp.py --niche beauty --apply

Returns 0 on full pass; non-zero on any failure with a
human-readable summary of which step broke.

This is a CONNECTIVITY smoke test, NOT a unit-test suite.
It exercises the live API path that pytest's mocked
tests can't reach.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path


# Ensure the repo root is on sys.path so `core.*` and
# `engines.*` import cleanly when this script is run
# directly (vs. via the installed package).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ── Config / env loading ────────────────────────────────────


def _load_dotenv(path: str = ".env") -> None:
    """Minimal .env loader -- no python-dotenv dep."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        v = v.strip().strip('"').strip("'")
        os.environ.setdefault(k.strip(), v)


# ── Result tracking ─────────────────────────────────────────


class Report:
    def __init__(self) -> None:
        self.checks: list[tuple[str, bool, str]] = []

    def add(
        self, name: str, ok: bool, detail: str = "",
    ) -> None:
        marker = "OK " if ok else "FAIL"
        # Use ASCII; no fancy glyphs (CLAUDE.md feedback).
        print(f"  [{marker}] {name}  {detail}")
        self.checks.append((name, ok, detail))

    def all_passed(self) -> bool:
        return all(ok for _, ok, _ in self.checks)

    def summary(self) -> str:
        passed = sum(1 for _, ok, _ in self.checks if ok)
        total = len(self.checks)
        return f"{passed} / {total} checks passed"


# ── Checks ──────────────────────────────────────────────────


def check_env(report: Report) -> bool:
    shop = os.environ.get("SHOPAI_SHOPIFY_URL", "").strip()
    key = os.environ.get("SHOPAI_SHOPIFY_KEY", "").strip()
    if not shop:
        report.add(
            "env SHOPAI_SHOPIFY_URL",
            False, "(not set)",
        )
        return False
    if not key:
        report.add(
            "env SHOPAI_SHOPIFY_KEY",
            False, "(not set)",
        )
        return False
    report.add(
        "env SHOPAI_SHOPIFY_URL", True,
        f"-> {shop}",
    )
    report.add(
        "env SHOPAI_SHOPIFY_KEY", True,
        f"-> {key[:10]}...{key[-4:]}",
    )
    return True


def check_shopify_api(report: Report) -> bool:
    """Hit shop.json to verify the token is live."""
    import json
    import urllib.error
    import urllib.request

    shop = os.environ["SHOPAI_SHOPIFY_URL"]
    key = os.environ["SHOPAI_SHOPIFY_KEY"]
    url = f"https://{shop}/admin/api/2024-01/shop.json"
    req = urllib.request.Request(
        url,
        headers={
            "X-Shopify-Access-Token": key,
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        info = data.get("shop", {})
        detail = (
            f"shop='{info.get('name', '?')}' "
            f"plan={info.get('plan_name', '?')} "
            f"currency={info.get('currency', '?')}"
        )
        report.add(
            "shopify api token", True, detail,
        )
        return True
    except urllib.error.HTTPError as e:
        report.add(
            "shopify api token", False,
            f"HTTP {e.code} {e.reason}",
        )
        return False
    except Exception as e:  # noqa: BLE001
        report.add(
            "shopify api token", False,
            f"{type(e).__name__}: {e}",
        )
        return False


def check_engine_layer(report: Report) -> bool:
    """Engine layer modules import cleanly."""
    try:
        from engines.store_setup import (  # noqa: F401
            collection_seeder,
            page_generator,
            policy_generator,
            launch_audit,
        )
    except Exception as e:  # noqa: BLE001
        report.add(
            "engine layer import", False,
            f"{type(e).__name__}: {e}",
        )
        return False
    report.add(
        "engine layer import", True,
        "(collection_seeder + page_generator + "
        "policy_generator + launch_audit)",
    )
    return True


def check_mcp_tools(
    report: Report, niche: str, store_name: str,
) -> bool:
    """Each recommend_* MCP tool returns ok envelope."""
    try:
        from core.mcp_server import tools
    except Exception as e:  # noqa: BLE001
        report.add(
            "mcp_server.tools import", False,
            f"{type(e).__name__}: {e}",
        )
        return False
    report.add(
        "mcp_server.tools import", True,
        f"({len(tools.REGISTERED_TOOLS)} tools "
        "registered)",
    )

    # Each on-main recommend_* tool should return ok.
    cases = [
        ("list_niches", {}),
        (
            "recommend_starter_collections",
            {"niche": niche},
        ),
        (
            "recommend_pages",
            {
                "store_name": store_name,
                "niche": niche,
            },
        ),
        (
            "recommend_policies",
            {
                "store_name": store_name,
                "niche": niche,
                "region": "us",
            },
        ),
        (
            "recommend_full_launch_pack",
            {
                "store_name": store_name,
                "niche": niche,
            },
        ),
    ]
    all_ok = True
    for tool_name, kwargs in cases:
        fn = getattr(tools, tool_name, None)
        if fn is None:
            report.add(
                f"mcp tool {tool_name}", False,
                "tool not found in module",
            )
            all_ok = False
            continue
        try:
            out = fn(**kwargs)
            status = out.get("status")
            if status == "ok":
                report.add(
                    f"mcp tool {tool_name}", True,
                    f"-> status=ok",
                )
            else:
                report.add(
                    f"mcp tool {tool_name}", False,
                    f"-> status={status} "
                    f"error={out.get('error')}",
                )
                all_ok = False
        except Exception as e:  # noqa: BLE001
            report.add(
                f"mcp tool {tool_name}", False,
                f"{type(e).__name__}: {e}",
            )
            all_ok = False
    return all_ok


def check_audit_against_live_store(
    report: Report,
) -> bool:
    """Run audit_launch_readiness against the live store."""
    try:
        from core.mcp_server.tools import (
            audit_launch_readiness,
        )
        out = audit_launch_readiness()
    except Exception as e:  # noqa: BLE001
        report.add(
            "audit_launch_readiness (live)", False,
            f"{type(e).__name__}: {e}",
        )
        return False
    status = out.get("status")
    if status != "ok":
        report.add(
            "audit_launch_readiness (live)", False,
            f"status={status} error={out.get('error')}",
        )
        return False
    data = out.get("data", {})
    pct = data.get("completion_pct", 0)
    ready = data.get("ready_to_launch", False)
    report.add(
        "audit_launch_readiness (live)", True,
        f"completion={pct}% ready={ready}",
    )
    return True


def check_apply_announcement_bar(
    report: Report, niche: str, store_name: str,
) -> bool:
    """Write check: create an announcement-bar page.

    Run only when --apply is passed. This is the
    LIGHTEST write -- a single page; if the module
    isn't merged the tool returns engine_unavailable
    cleanly without breaking the store.
    """
    try:
        from core.mcp_server.extended_tools import (
            apply_announcement_bar,
        )
    except Exception as e:  # noqa: BLE001
        report.add(
            "apply_announcement_bar import", False,
            f"{type(e).__name__}: {e}",
        )
        return False
    try:
        out = apply_announcement_bar(
            store_name=store_name, niche=niche,
        )
    except Exception as e:  # noqa: BLE001
        report.add(
            "apply_announcement_bar (live write)",
            False,
            f"{type(e).__name__}: {e}",
        )
        return False
    status = out.get("status")
    if status == "ok":
        d = out.get("data", {})
        report.add(
            "apply_announcement_bar (live write)",
            bool(d.get("applied")),
            (
                f"applied={d.get('applied')} "
                f"handle={d.get('handle')} "
                f"error={d.get('error')}"
            ),
        )
        return bool(d.get("applied"))
    # engine_unavailable means the announcement_bar
    # module isn't on main yet -- not a failure of the
    # smoke test, just a "skip with explanation".
    err = out.get("error", "")
    if "engine_unavailable" in err:
        report.add(
            "apply_announcement_bar (live write)",
            True,
            "skipped: module not on main yet "
            f"({err})",
        )
        return True
    report.add(
        "apply_announcement_bar (live write)",
        False,
        f"status={status} error={err}",
    )
    return False


# ── Main ────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "End-to-end smoke test for ShopAI's MCP "
            "tool surface against a real Shopify "
            "dev store."
        ),
    )
    parser.add_argument(
        "--niche", default="beauty",
        help="Niche key to use for recommend tests "
        "(default: beauty)",
    )
    parser.add_argument(
        "--store-name", default="ShopAI Smoke Test",
        help="Display name for the test store (default: "
        "'ShopAI Smoke Test')",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Perform ONE light write "
        "(apply_announcement_bar). Default is dry-run.",
    )
    parser.add_argument(
        "--env-file", default=".env",
        help="Path to .env file (default: .env)",
    )
    args = parser.parse_args()

    _load_dotenv(args.env_file)

    report = Report()
    print(
        "ShopAI MCP smoke test "
        f"(niche={args.niche}, "
        f"store={args.store_name}, "
        f"apply={args.apply})\n"
    )

    started = time.monotonic()

    # 1-2: env + token
    env_ok = check_env(report)
    if not env_ok:
        print(
            f"\n{report.summary()}  "
            "(stopped early -- no Shopify creds)",
        )
        return 2
    token_ok = check_shopify_api(report)
    if not token_ok:
        print(
            f"\n{report.summary()}  "
            "(stopped early -- token failed)",
        )
        return 2

    # 3: engine layer
    check_engine_layer(report)

    # 4: MCP tools (dry run)
    check_mcp_tools(
        report, args.niche, args.store_name,
    )

    # 5: live audit
    check_audit_against_live_store(report)

    # 6: optional live write
    if args.apply:
        check_apply_announcement_bar(
            report, args.niche, args.store_name,
        )
    else:
        report.add(
            "apply_announcement_bar",
            True,
            "skipped (use --apply to enable)",
        )

    elapsed = time.monotonic() - started
    print(
        f"\n{report.summary()} "
        f"(elapsed={elapsed:.1f}s)"
    )
    return 0 if report.all_passed() else 1


if __name__ == "__main__":
    sys.exit(main())
