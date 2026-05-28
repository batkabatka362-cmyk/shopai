"""Pattern T audit: autonomy env knob registry (W185).

Each autonomy domain ships ~5-7 env-var knobs:

  SHOPAI_AUTO_PAUSE_{PREFIX}_ON_FAILURE
  SHOPAI_{PREFIX}_WARN_FAILURE_RATIO
  SHOPAI_{PREFIX}_PAUSE_FAILURE_RATIO
  SHOPAI_{PREFIX}_HEALTH_MIN_SAMPLE
  SHOPAI_{PREFIX}_AUTO_RESUME_HOURS
  + domain-specific caps

Operators discovered these knobs by reading commit messages
or grepping CLAUDE.md. Pattern T builds a registry of every
expected env var per domain + verifies they're actually
referenced from the codebase (so future PRs that add a knob
without registering it get caught).

The registry doubles as documentation: ``shopai autonomy-env``
(Wave 186) lists every knob with its current value.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# Per-domain expected env knobs. Each value is a list of env
# var names. Standard health knobs are auto-generated from
# the env_prefix.
_STANDARD_HEALTH_KNOBS = (
    "SHOPAI_AUTO_PAUSE_{PREFIX}_ON_FAILURE",
    "SHOPAI_{PREFIX}_WARN_FAILURE_RATIO",
    "SHOPAI_{PREFIX}_PAUSE_FAILURE_RATIO",
    "SHOPAI_{PREFIX}_HEALTH_MIN_SAMPLE",
    "SHOPAI_{PREFIX}_AUTO_RESUME_HOURS",
)

# Domains with (env_prefix, extra_knobs) tuples
_DOMAINS: dict[str, tuple[str, list[str]]] = {
    "customer_support_refund": (
        "REFUND",
        [
            "SHOPAI_REFUND_MAX_AMOUNT_USD",
            "SHOPAI_REFUND_MAX_FRAUD_RISK",
        ],
    ),
    "marketing_budget": (
        "BUDGET",
        ["SHOPAI_BUDGET_MAX_DELTA_USD"],
    ),
    "fulfillment": ("FULFILLMENT", []),
    "inventory": (
        "INVENTORY",
        [
            "SHOPAI_INVENTORY_MAX_QUANTITY",
            "SHOPAI_INVENTORY_MIN_DELTA",
        ],
    ),
    "discount_cleanup": (
        "DISCOUNT_CLEANUP",
        [
            "SHOPAI_DISCOUNT_CLEANUP_MIN_AGE_DAYS",
            "SHOPAI_DISCOUNT_CLEANUP_MAX_PER_RUN",
        ],
    ),
    "order_followup": ("ORDER_FOLLOWUP", []),
    "product_seo": (
        "PRODUCT_SEO",
        ["SHOPAI_PRODUCT_SEO_MAX_LENGTH"],
    ),
    "customer_outreach": (
        "CUSTOMER_OUTREACH",
        ["SHOPAI_CUSTOMER_OUTREACH_MAX_PER_RUN"],
    ),
}


@dataclass
class EnvKnob:
    name: str
    domain: str
    current_value: str | None = None


@dataclass
class PatternTReport:
    domains_scanned: list[str] = field(default_factory=list)
    knobs: list[EnvKnob] = field(default_factory=list)
    set_knobs: list[EnvKnob] = field(default_factory=list)

    @property
    def total_knobs(self) -> int:
        return len(self.knobs)

    @property
    def set_count(self) -> int:
        return len(self.set_knobs)


def _expand_knobs(prefix: str, extras: list[str]) -> list[str]:
    out: list[str] = []
    for tpl in _STANDARD_HEALTH_KNOBS:
        out.append(tpl.replace("{PREFIX}", prefix))
    out.extend(extras)
    return out


def build_autonomy_env_registry() -> PatternTReport:
    """Build the canonical registry of every autonomy env knob
    + current value from os.environ."""
    report = PatternTReport()
    for domain, (prefix, extras) in _DOMAINS.items():
        report.domains_scanned.append(domain)
        for var_name in _expand_knobs(prefix, extras):
            value = os.environ.get(var_name)
            knob = EnvKnob(
                name=var_name,
                domain=domain,
                current_value=value,
            )
            report.knobs.append(knob)
            if value is not None:
                report.set_knobs.append(knob)
    return report


def run_pattern_t_audit() -> PatternTReport:
    """Pattern T entry point. Currently builds the registry --
    future versions can add CI-time verification that each
    registry entry is grepable in the engines/ codebase."""
    return build_autonomy_env_registry()
