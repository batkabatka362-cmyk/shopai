"""W963-111: every core/adapters/<category>/bootstrap.py module
must be invoked by cli._maybe_bootstrap_secondary_adapters at
startup.

This is a regression guard against the bug class introduced
in W963-106 and re-surfaced in W963-111: an adapter directory
exists with a fully-functional bootstrap.py, but
cli._maybe_bootstrap_secondary_adapters never imports it. As
a result, adapters never instantiate at CLI startup and the
router has no path to route through even when credentials
are present.

Pre-fix history:
  * W963-106 fixed 7 missing chains (sourcing / video_gen /
    voice / reviews / sms / translation / scraper).
  * W963-111 fixed 5 more (ads_spy / image / image_cdn /
    payment / obsidian).

This test discovers every bootstrap.py module in
core/adapters/<category>/ and asserts the orchestrator
references it. Adding a new category but forgetting to wire
it will break this test immediately.

Two categories are intentionally exempted from the
auto-invocation orchestrator:
  * shopify: separate per-store credential resolution path
    (cli._maybe_bootstrap_shopify_adapters) -- see Wave 45.
"""
from __future__ import annotations

import ast
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
_ADAPTERS_DIR = _REPO_ROOT / "core" / "adapters"
_CLI_PATH = _REPO_ROOT / "cli.py"


# Categories handled by a separate, more privileged
# bootstrap chain (per-store credential resolution).
_EXEMPT_CATEGORIES = frozenset({
    "shopify",
})


def _discover_bootstrap_categories() -> set[str]:
    """Return the names of every adapter category that has a
    bootstrap.py module."""
    out: set[str] = set()
    for child in _ADAPTERS_DIR.iterdir():
        if not child.is_dir():
            continue
        if (child / "bootstrap.py").is_file():
            out.add(child.name)
    return out


def _orchestrator_referenced_categories() -> set[str]:
    """Parse cli.py and find which adapter categories the
    _maybe_bootstrap_secondary_adapters function imports a
    bootstrap module from."""
    src = _CLI_PATH.read_text(encoding="utf-8")
    tree = ast.parse(src)

    # Find the _maybe_bootstrap_secondary_adapters function
    target_fn: ast.FunctionDef | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and (
            node.name == "_maybe_bootstrap_secondary_adapters"
        ):
            target_fn = node
            break
    assert target_fn is not None, (
        "cli._maybe_bootstrap_secondary_adapters is missing"
    )

    referenced: set[str] = set()
    for n in ast.walk(target_fn):
        if isinstance(n, ast.ImportFrom):
            # match: from core.adapters.<category>.bootstrap
            #        import register_all
            mod = n.module or ""
            if (
                mod.startswith("core.adapters.")
                and mod.endswith(".bootstrap")
            ):
                # e.g. core.adapters.voice.bootstrap -> voice
                parts = mod.split(".")
                if len(parts) >= 4:
                    referenced.add(parts[2])
    return referenced


def test_every_bootstrap_chain_is_wired_into_orchestrator():
    """Every core/adapters/<category>/bootstrap.py must be
    referenced by cli._maybe_bootstrap_secondary_adapters
    (except for shopify, which has its own path)."""
    on_disk = _discover_bootstrap_categories()
    referenced = _orchestrator_referenced_categories()

    # Categories with a bootstrap.py that the orchestrator
    # should be invoking
    expected = on_disk - _EXEMPT_CATEGORIES
    missing = expected - referenced

    assert not missing, (
        "cli._maybe_bootstrap_secondary_adapters MUST "
        "invoke every adapter category's bootstrap "
        "chain. Missing wireups: "
        f"{sorted(missing)}.\n"
        "Add a try/except: pass block importing "
        "core.adapters.<category>.bootstrap.register_all "
        "and call it. See the W963-106 + W963-111 fixes "
        "for the canonical pattern."
    )


def test_orchestrator_references_only_real_categories():
    """Sanity: the orchestrator should not reference
    a category that does not exist on disk (typo guard)."""
    on_disk = _discover_bootstrap_categories()
    referenced = _orchestrator_referenced_categories()

    stale = referenced - on_disk
    assert not stale, (
        "cli._maybe_bootstrap_secondary_adapters "
        "references nonexistent adapter categories: "
        f"{sorted(stale)}"
    )


def test_no_duplicate_bootstrap_invocations():
    """Each category should be bootstrapped exactly once
    per CLI startup. Duplicate invocations waste work +
    can mask bugs that only fire on second registration."""
    src = _CLI_PATH.read_text(encoding="utf-8")
    tree = ast.parse(src)

    target_fn: ast.FunctionDef | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and (
            node.name == "_maybe_bootstrap_secondary_adapters"
        ):
            target_fn = node
            break
    assert target_fn is not None

    # Count each category's appearances
    counts: dict[str, int] = {}
    for n in ast.walk(target_fn):
        if isinstance(n, ast.ImportFrom):
            mod = n.module or ""
            if (
                mod.startswith("core.adapters.")
                and mod.endswith(".bootstrap")
            ):
                parts = mod.split(".")
                if len(parts) >= 4:
                    cat = parts[2]
                    counts[cat] = counts.get(cat, 0) + 1

    duplicates = {
        cat: n for cat, n in counts.items() if n > 1
    }
    assert not duplicates, (
        f"Duplicate bootstrap invocations: {duplicates}"
    )
