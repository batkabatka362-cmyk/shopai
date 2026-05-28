"""Pattern AL audit: pause-state file path uniqueness (W319).

Each autonomy domain's state module persists its pause flag to
a JSON file at ``data/<domain>_state.json``. If two domains
accidentally share the same path (copy-paste error in a new
domain's state module), pausing one silently
pauses/unpauses the other -- a sneaky cross-domain bug that
unit tests miss because each test exercises ONE domain.

Pattern AL imports each state module + reads its
``_STATE_PATH`` constant + asserts:
  1. every domain exports ``_STATE_PATH`` (string or PathLike)
  2. all 7 paths are pairwise distinct (no collisions)
  3. each path lives under ``data/`` (catches misconfiguration
     pointing at engines/ or other source dirs)

Companion to Pattern AE (state module exports is_paused).
Together they nail down the state-module contract: the symbol
exists AND it persists to the right unique location.
"""
from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from importlib import import_module

logger = logging.getLogger(__name__)


# Per-domain (display name, package, state module name).
# State modules expose a module-level _STATE_PATH constant.
_DOMAIN_STATE_MODULES: dict[str, tuple[str, str]] = {
    "customer_support_refund": (
        "returns_management", "refund_state",
    ),
    "marketing_budget": (
        "roas_guardrails", "budget_state",
    ),
    "fulfillment": (
        "fulfillment_autonomy", "fulfillment_state",
    ),
    "inventory": (
        "inventory_autonomy", "inventory_state",
    ),
    "discount_cleanup": (
        "discount_cleanup_autonomy", "cleanup_state",
    ),
    "order_followup": (
        "order_followup_autonomy", "followup_state",
    ),
    "product_seo": (
        "product_seo_autonomy", "seo_state",
    ),
}


@dataclass
class PatternALViolation:
    domain: str
    state_path: str = ""
    reason: str = ""


@dataclass
class PatternALReport:
    domains_scanned: list[str] = field(default_factory=list)
    clean_domains: list[str] = field(default_factory=list)
    violations: list[PatternALViolation] = field(
        default_factory=list,
    )
    paths_by_domain: dict[str, str] = field(
        default_factory=dict,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def _read_state_path(
    pkg: str, modname: str,
) -> tuple[str | None, str]:
    """Best-effort import + read ``_STATE_PATH``. Returns
    (path-as-str OR None, reason)."""
    try:
        mod = import_module(f"engines.{pkg}.{modname}")
    except Exception as exc:  # noqa: BLE001
        return None, f"import failed: {exc!s:.80}"
    path = getattr(mod, "_STATE_PATH", None)
    if path is None:
        return None, "module does not export _STATE_PATH"
    try:
        return str(path), ""
    except Exception as exc:  # noqa: BLE001
        return None, f"_STATE_PATH not str-able: {exc!s:.80}"


def run_pattern_al_audit() -> PatternALReport:
    """Verify every autonomy domain's pause-state JSON path
    is unique + lives under data/."""
    report = PatternALReport()

    # Step 1: collect per-domain paths
    for domain, (pkg, modname) in (
        _DOMAIN_STATE_MODULES.items()
    ):
        report.domains_scanned.append(domain)
        path, reason = _read_state_path(pkg, modname)
        if path is None:
            report.violations.append(PatternALViolation(
                domain=domain, reason=reason,
            ))
            continue
        # Normalize path for cross-platform comparison
        normalized = path.replace("\\", "/").lower()
        report.paths_by_domain[domain] = normalized

    # Step 2: detect collisions (same path used by 2+ domains)
    counts = Counter(report.paths_by_domain.values())
    colliding = {p for p, n in counts.items() if n > 1}

    # Step 3: enforce data/ prefix
    for domain, path in report.paths_by_domain.items():
        problems: list[str] = []
        if path in colliding:
            collide_with = [
                d for d, p in report.paths_by_domain.items()
                if p == path and d != domain
            ]
            problems.append(
                f"path collides with: {sorted(collide_with)}"
            )
        if not path.startswith("data/"):
            problems.append(
                "path does not start with 'data/'"
            )
        if problems:
            report.violations.append(PatternALViolation(
                domain=domain,
                state_path=path,
                reason="; ".join(problems),
            ))
        else:
            report.clean_domains.append(domain)

    return report
