"""ShopAI MCP tool definitions.

Each function here is exposed to Claude as a callable MCP
tool. The function does three things:

  1. Validates its arguments.
  2. Calls into the existing engine / adapter layer.
  3. Returns a JSON-serialisable dict.

Engine imports are LAZY (inside the function body) so the
MCP server boots even when an engine module isn't
available -- the tool will return a clean ``error`` dict
in that case instead of failing at startup.

Tool naming convention:

  * ``shopai.recommend_*`` -- pure-content recommendations
    (no Shopify writes). Always available; useful for
    "show me what would happen".
  * ``shopai.apply_*`` -- writes to Shopify via the
    adapter layer. Requires the router to be configured
    (i.e. a real store connected).
  * ``shopai.audit_*`` -- read-only checks against a
    live store.

Each tool's return dict carries:
  * ``status``: "ok" | "error" | "not_implemented"
  * ``data``: the payload (the actual recommendation /
    audit / apply result)
  * ``error``: human-readable error string when status
    is "error"
"""
from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ── Tool registry ────────────────────────────────────────────


ToolFn = Callable[..., dict[str, Any]]


def _ok(data: Any) -> dict[str, Any]:
    return {"status": "ok", "data": data, "error": None}


def _err(msg: str) -> dict[str, Any]:
    return {"status": "error", "data": None, "error": msg}


def _validate_niche(niche: str) -> str:
    """Niche cleanup -- lower + strip + general fallback."""
    n = (niche or "").strip().lower() or "general"
    return n


def _validate_store_name(store_name: str) -> str | None:
    name = (store_name or "").strip()
    if not name:
        return None
    return name


# ── Generic helpers ─────────────────────────────────────────


def list_niches() -> dict[str, Any]:
    """Return the niche keys ShopAI currently supports.

    Niches are the structural primitive that shapes every
    recommendation. Claude can call this to know what
    values to pass as ``niche`` to other tools.
    """
    return _ok({
        "niches": [
            "beauty", "fashion", "tech", "home", "food",
            "pets", "fitness", "jewelry", "outdoor",
            "baby", "general",
        ],
        "fallback": "general",
        "note": (
            "Unknown niches fall back to general's "
            "templates. Pass the closest match -- or "
            "general -- for niches not in this list."
        ),
    })


def health() -> dict[str, Any]:
    """Basic health-check tool. Useful from Claude to
    confirm the MCP server is actually responding."""
    return _ok({
        "service": "shopai-mcp",
        "version": "0.1.0",
        "tool_count": len(REGISTERED_TOOLS),
    })


# ── Content recommendation tools ────────────────────────────


def recommend_starter_collections(
    *, niche: str = "general",
) -> dict[str, Any]:
    """Recommend niche-aware starter collections.

    Returns the structured collection specs (title / handle
    / description_html / sort_order) that
    ``collection_seeder.apply_starter_collections`` would
    push to Shopify.
    """
    niche_n = _validate_niche(niche)
    try:
        from engines.store_setup.collection_seeder import (
            generate_starter_collections,
        )
    except Exception as exc:  # noqa: BLE001
        return _err(f"engine_import_failed: {exc}")
    try:
        specs = generate_starter_collections(niche=niche_n)
    except Exception as exc:  # noqa: BLE001
        return _err(f"generator_raised: {exc}")
    return _ok({"niche": niche_n, "collections": specs})


def recommend_pages(
    *,
    store_name: str,
    niche: str = "general",
    founder_name: str | None = None,
    support_email: str | None = None,
) -> dict[str, Any]:
    """Recommend the 4 standard storefront pages
    (About / Contact / FAQ / Shipping & Returns).
    """
    name = _validate_store_name(store_name)
    if not name:
        return _err("store_name_required")
    niche_n = _validate_niche(niche)
    try:
        from engines.store_setup.page_generator import (
            generate_pages,
        )
    except Exception as exc:  # noqa: BLE001
        return _err(f"engine_import_failed: {exc}")
    try:
        # support_email may not be plumbed in the on-main
        # version of generate_pages; pass it via kwargs
        # only when accepted.
        kwargs: dict[str, Any] = {
            "store_name": name,
            "niche": niche_n,
        }
        if founder_name:
            kwargs["founder_name"] = founder_name
        if support_email:
            kwargs["support_email"] = support_email
        try:
            pages = generate_pages(**kwargs)
        except TypeError:
            # Older signature: drop support_email
            kwargs.pop("support_email", None)
            pages = generate_pages(**kwargs)
    except Exception as exc:  # noqa: BLE001
        return _err(f"generator_raised: {exc}")
    return _ok({"niche": niche_n, "pages": pages})


def recommend_policies(
    *,
    store_name: str,
    niche: str = "general",
    region: str = "us",
    include_legal_notice: bool = False,
    include_subscription_policy: bool = False,
) -> dict[str, Any]:
    """Recommend the 5 essential legal policies."""
    name = _validate_store_name(store_name)
    if not name:
        return _err("store_name_required")
    niche_n = _validate_niche(niche)
    try:
        from engines.store_setup.policy_generator import (
            generate_policies,
        )
    except Exception as exc:  # noqa: BLE001
        return _err(f"engine_import_failed: {exc}")
    try:
        policies = generate_policies(
            store_name=name,
            niche=niche_n,
            region=(region or "us").strip().lower(),
            include_legal_notice=bool(
                include_legal_notice,
            ),
            include_subscription_policy=bool(
                include_subscription_policy,
            ),
        )
    except Exception as exc:  # noqa: BLE001
        return _err(f"generator_raised: {exc}")
    return _ok({
        "niche": niche_n,
        "region": region,
        "policies": policies,
    })


# ── Audit tools ──────────────────────────────────────────────


def audit_launch_readiness(
    *,
    store_id: str | None = None,
    expected_collections: int = 1,
    expected_discounts: int = 1,
) -> dict[str, Any]:
    """Run the read-only launch-readiness audit on a
    live Shopify store.

    Returns the full audit report -- per-check status,
    completion_pct, missing items. Claude can summarise
    this for the operator or chain into apply_* tools
    to fix the gaps.
    """
    try:
        from engines.store_setup.launch_audit import (
            audit_store,
        )
    except Exception as exc:  # noqa: BLE001
        return _err(f"engine_import_failed: {exc}")
    try:
        report = audit_store(
            store_id=store_id,
            expected_collections=int(
                expected_collections,
            ),
            expected_discounts=int(expected_discounts),
        )
    except Exception as exc:  # noqa: BLE001
        return _err(f"audit_raised: {exc}")
    return _ok(report)


# ── Write tools (apply to Shopify) ──────────────────────────


def apply_starter_collections(
    *,
    niche: str = "general",
    store_id: str | None = None,
) -> dict[str, Any]:
    """Generate + push niche-aware starter collections
    to Shopify via SHOPIFY_CREATE_COLLECTION."""
    niche_n = _validate_niche(niche)
    try:
        from engines.store_setup.collection_seeder import (
            apply_starter_collections as _apply,
            generate_starter_collections,
        )
    except Exception as exc:  # noqa: BLE001
        return _err(f"engine_import_failed: {exc}")
    try:
        specs = generate_starter_collections(niche=niche_n)
        result = _apply(specs, store_id=store_id)
    except Exception as exc:  # noqa: BLE001
        return _err(f"applier_raised: {exc}")
    return _ok(result)


def apply_pages(
    *,
    store_name: str,
    niche: str = "general",
    founder_name: str | None = None,
    support_email: str | None = None,
    store_id: str | None = None,
) -> dict[str, Any]:
    """Generate + push the 4 standard pages to Shopify."""
    name = _validate_store_name(store_name)
    if not name:
        return _err("store_name_required")
    niche_n = _validate_niche(niche)
    try:
        from engines.store_setup.page_generator import (
            generate_pages,
        )
        from engines.store_setup.page_applier import (
            apply_pages as _apply,
        )
    except Exception as exc:  # noqa: BLE001
        return _err(f"engine_import_failed: {exc}")
    try:
        kwargs: dict[str, Any] = {
            "store_name": name,
            "niche": niche_n,
        }
        if founder_name:
            kwargs["founder_name"] = founder_name
        if support_email:
            kwargs["support_email"] = support_email
        try:
            pages = generate_pages(**kwargs)
        except TypeError:
            kwargs.pop("support_email", None)
            pages = generate_pages(**kwargs)
        result = _apply(pages, store_id=store_id)
    except Exception as exc:  # noqa: BLE001
        return _err(f"applier_raised: {exc}")
    return _ok(result)


def apply_policies(
    *,
    store_name: str,
    niche: str = "general",
    region: str = "us",
    include_legal_notice: bool = False,
    include_subscription_policy: bool = False,
    store_id: str | None = None,
) -> dict[str, Any]:
    """Generate + push the 5 essential legal policies."""
    name = _validate_store_name(store_name)
    if not name:
        return _err("store_name_required")
    niche_n = _validate_niche(niche)
    try:
        from engines.store_setup.policy_generator import (
            generate_policies,
        )
        from engines.store_setup.policy_applier import (
            apply_policies as _apply,
        )
    except Exception as exc:  # noqa: BLE001
        return _err(f"engine_import_failed: {exc}")
    try:
        policies = generate_policies(
            store_name=name,
            niche=niche_n,
            region=(region or "us").strip().lower(),
            include_legal_notice=bool(
                include_legal_notice,
            ),
            include_subscription_policy=bool(
                include_subscription_policy,
            ),
        )
        result = _apply(policies, store_id=store_id)
    except Exception as exc:  # noqa: BLE001
        return _err(f"applier_raised: {exc}")
    return _ok(result)


# ── Full-launch composite tool ──────────────────────────────


def recommend_full_launch_pack(
    *,
    store_name: str,
    niche: str = "general",
    region: str = "us",
) -> dict[str, Any]:
    """Bundle every available niche-aware recommendation
    into one response.

    Useful for Claude to show "here's everything ShopAI
    would set up for your store" in a single tool call
    instead of fanning out across ``recommend_*`` calls
    individually.
    """
    name = _validate_store_name(store_name)
    if not name:
        return _err("store_name_required")
    niche_n = _validate_niche(niche)

    bundle: dict[str, Any] = {
        "store_name": name,
        "niche": niche_n,
        "region": region,
    }

    # Wrap each generator -- a failure in one shouldn't
    # block the others. Each section ends up either
    # populated OR carrying a per-section error.
    bundle["collections"] = _safe_call(
        recommend_starter_collections,
        niche=niche_n,
    )
    bundle["pages"] = _safe_call(
        recommend_pages,
        store_name=name, niche=niche_n,
    )
    bundle["policies"] = _safe_call(
        recommend_policies,
        store_name=name, niche=niche_n, region=region,
    )

    return _ok(bundle)


def _safe_call(fn: ToolFn, **kwargs: Any) -> dict[str, Any]:
    try:
        return fn(**kwargs)
    except Exception as exc:  # noqa: BLE001
        return _err(f"{fn.__name__} raised: {exc}")


# ── Tool registry ───────────────────────────────────────────


# Order matters: tools listed here are exposed to Claude
# in this order via ``REGISTERED_TOOLS``. Display friendly
# tool names matching the Anthropic Shopify connector
# naming convention (snake_case, no namespace prefix --
# the MCP server name itself acts as the namespace).
REGISTERED_TOOLS: list[tuple[str, ToolFn, str]] = [
    (
        "list_niches",
        list_niches,
        "List the niche keys ShopAI currently supports.",
    ),
    (
        "health",
        health,
        "Health check -- confirm the ShopAI MCP server "
        "is responding.",
    ),
    (
        "recommend_starter_collections",
        recommend_starter_collections,
        "Recommend niche-aware starter collections for "
        "a fresh Shopify store.",
    ),
    (
        "recommend_pages",
        recommend_pages,
        "Recommend the 4 standard storefront pages "
        "(About / Contact / FAQ / Shipping & Returns) "
        "for a niche.",
    ),
    (
        "recommend_policies",
        recommend_policies,
        "Recommend the 5 essential legal policies for "
        "a niche + region.",
    ),
    (
        "recommend_full_launch_pack",
        recommend_full_launch_pack,
        "Bundle every available niche-aware "
        "recommendation in one response.",
    ),
    (
        "audit_launch_readiness",
        audit_launch_readiness,
        "Read-only check: which launch-readiness items "
        "are done vs missing on a live Shopify store.",
    ),
    (
        "apply_starter_collections",
        apply_starter_collections,
        "Push niche-aware starter collections to a live "
        "Shopify store via SHOPIFY_CREATE_COLLECTION.",
    ),
    (
        "apply_pages",
        apply_pages,
        "Push the 4 standard storefront pages to a live "
        "Shopify store via SHOPIFY_CREATE_PAGE.",
    ),
    (
        "apply_policies",
        apply_policies,
        "Push the 5 essential legal policies to a live "
        "Shopify store via SHOPIFY_UPDATE_SHOP_POLICY.",
    ),
]
