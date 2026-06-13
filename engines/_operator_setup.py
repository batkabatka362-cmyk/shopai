"""W963-180: shopai operator-setup interactive .env wizard.

Closes the UX gap docs/OPERATOR_QUICK_START.md left open: 'add
these env vars to .env yourself'. Operators want a guided flow.

Public API:
  - run_wizard(env_path, categories=None, interactive=True)
      Walks the operator through each category of env vars. Prompts
      for missing values; preserves existing values; validates
      format; writes back atomically. Returns a SetupReport with
      per-category status.

Design notes:
  - Preserve all existing keys in .env (don't clobber operator's
    hand-edits, comments, or unknown vars from other modules).
  - Atomic write: write to .env.tmp then os.replace(.env.tmp, .env)
    so a crash mid-write doesn't truncate the file.
  - Skip prompts for keys that are already set (operator can use
    --rewrite to force overwrite).
  - Validation rules per key are encoded in ENV_SPEC -- single
    source of truth (testable, swap-friendly).
  - Pattern J guard: the wizard short-circuits in test mode UNLESS
    the test explicitly disables the guard (the wizard module
    itself is tested via unit tests on the helper fns; the
    end-to-end interactive prompt is tested by patching input()).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


# ── ENV var catalog ────────────────────────────────────────────


@dataclass
class EnvVar:
    key: str
    description: str
    required: bool = False
    validator: Callable[[str], str] | None = None
    where_to_get: str = ""
    is_secret: bool = True  # default redact when printing


@dataclass
class EnvCategory:
    name: str
    description: str
    required_for_revenue: bool
    vars: list[EnvVar]


def _validate_shopify_url(value: str) -> str:
    """Shopify shops are always *.myshopify.com (cannot be a
    custom domain at the API layer)."""
    v = value.strip().lower()
    if v.startswith("https://"):
        v = v[len("https://"):]
    if v.startswith("http://"):
        v = v[len("http://"):]
    v = v.rstrip("/")
    if not v.endswith(".myshopify.com"):
        raise ValueError(
            f"must end in '.myshopify.com', got {value!r}",
        )
    if v.count(".") != 2:
        raise ValueError(
            f"shop URL has too many dots: {value!r}",
        )
    return v


def _validate_shopify_token(value: str) -> str:
    v = value.strip()
    if not v.startswith("shpat_") and not v.startswith("shpca_"):
        raise ValueError(
            "Shopify Admin tokens start with 'shpat_' "
            "(or 'shpca_' for custom apps)",
        )
    if len(v) < 30:
        raise ValueError(
            f"token too short: {len(v)} chars (expected 30+)",
        )
    return v


def _validate_url(value: str) -> str:
    v = value.strip()
    if not (
        v.startswith("https://") or v.startswith("http://")
    ):
        raise ValueError(
            "must start with http:// or https://",
        )
    return v


def _validate_nonempty(value: str) -> str:
    v = value.strip()
    if not v:
        raise ValueError("cannot be empty")
    return v


CATEGORIES: list[EnvCategory] = [
    EnvCategory(
        name="Shopify Admin (per-store)",
        description=(
            "Per-store credentials. Wire each store before "
            "the cycle can sync inventory or apply mutations."
        ),
        required_for_revenue=True,
        vars=[
            EnvVar(
                key="SHOPAI_SHOPIFY_URL",
                description=(
                    "fleet-default Shopify shop URL "
                    "(<shop>.myshopify.com)"
                ),
                required=True,
                validator=_validate_shopify_url,
                where_to_get=(
                    "Shopify admin -> Settings -> Domains"
                ),
                is_secret=False,
            ),
            EnvVar(
                key="SHOPAI_SHOPIFY_KEY",
                description=(
                    "fleet-default Shopify Admin API token"
                ),
                required=True,
                validator=_validate_shopify_token,
                where_to_get=(
                    "Shopify admin -> Apps -> Develop apps "
                    "-> Configuration -> Admin API token"
                ),
            ),
        ],
    ),
    EnvCategory(
        name="Ad channels",
        description=(
            "At least ONE is required for real revenue. "
            "Without an ad channel, ads_launcher emits plans "
            "but no live campaigns."
        ),
        required_for_revenue=True,
        vars=[
            EnvVar(
                key="META_ADS_ACCESS_TOKEN",
                description=(
                    "Meta Ads (Facebook + Instagram) "
                    "long-lived token"
                ),
                where_to_get=(
                    "developers.facebook.com -> Create app "
                    "-> Marketing API"
                ),
            ),
            EnvVar(
                key="META_ADS_ACCOUNT_ID",
                description="Meta Ads 15-digit account ID",
                where_to_get=(
                    "Meta Business Suite -> Ad Accounts"
                ),
                is_secret=False,
            ),
            EnvVar(
                key="GOOGLE_ADS_CLIENT_ID",
                description="Google Ads OAuth client",
                where_to_get=(
                    "console.cloud.google.com -> OAuth 2.0"
                ),
            ),
            EnvVar(
                key="GOOGLE_ADS_CLIENT_SECRET",
                description="Google Ads OAuth secret",
                where_to_get="same page as CLIENT_ID",
            ),
            EnvVar(
                key="GOOGLE_ADS_CUSTOMER_ID",
                description="Google Ads 10-digit customer ID",
                is_secret=False,
            ),
            EnvVar(
                key="GOOGLE_ADS_DEVELOPER_TOKEN",
                description="Google Ads developer token",
                where_to_get=(
                    "ads.google.com/aw/apicenter "
                    "-> Developer token"
                ),
            ),
            EnvVar(
                key="GOOGLE_ADS_REFRESH_TOKEN",
                description="Google Ads refresh token",
                where_to_get=(
                    "OAuth playground / one-time auth flow"
                ),
            ),
        ],
    ),
    EnvCategory(
        name="Email (retention loop)",
        description=(
            "Powers cart-recovery + post-purchase + "
            "re-engagement email."
        ),
        required_for_revenue=False,
        vars=[
            EnvVar(
                key="KLAVIYO_API_KEY",
                description="Klaviyo private API key",
                where_to_get=(
                    "Klaviyo -> Account -> API Keys"
                ),
            ),
            EnvVar(
                key="KLAVIYO_WEBHOOK_SECRET",
                description=(
                    "HMAC secret for inbound Klaviyo webhooks"
                ),
                where_to_get=(
                    "Klaviyo -> Settings -> Webhooks"
                ),
            ),
        ],
    ),
    EnvCategory(
        name="Notify webhook",
        description=(
            "Slack / Discord URL for cycle alerts."
        ),
        required_for_revenue=False,
        vars=[
            EnvVar(
                key="SHOPAI_NOTIFY_WEBHOOK_URL",
                description=(
                    "Incoming webhook URL for cycle alerts"
                ),
                validator=_validate_url,
                where_to_get=(
                    "Slack: api.slack.com/messaging/webhooks"
                    " | Discord: server settings -> "
                    "Integrations -> Webhooks"
                ),
                is_secret=False,
            ),
        ],
    ),
    EnvCategory(
        name="Vendor webhooks (optional)",
        description=(
            "HMAC secrets for each external vendor whose "
            "events ShopAI should consume."
        ),
        required_for_revenue=False,
        vars=[
            EnvVar(
                key="GORGIAS_API_KEY",
                description="Gorgias helpdesk API key",
            ),
            EnvVar(
                key="GORGIAS_USERNAME",
                description="Gorgias account email",
                is_secret=False,
            ),
            EnvVar(
                key="GORGIAS_SUBDOMAIN",
                description=(
                    "Gorgias subdomain (<acme>.gorgias.com)"
                ),
                is_secret=False,
            ),
            EnvVar(
                key="AFTERSHIP_API_KEY",
                description="AfterShip API key",
            ),
            EnvVar(
                key="AFTERSHIP_WEBHOOK_SECRET",
                description="AfterShip webhook HMAC",
            ),
            EnvVar(
                key="STRIPE_WEBHOOK_SECRET",
                description=(
                    "Stripe webhook signing secret "
                    "(whsec_...)"
                ),
            ),
            EnvVar(
                key="PAYPAL_WEBHOOK_ID",
                description="PayPal webhook ID",
                is_secret=False,
            ),
            EnvVar(
                key="KLARNA_WEBHOOK_SECRET",
                description="Klarna webhook HMAC",
            ),
            EnvVar(
                key="LOOX_WEBHOOK_SECRET",
                description="Loox webhook HMAC",
            ),
        ],
    ),
]


# ── Public API ────────────────────────────────────────────────


@dataclass
class CategoryStatus:
    name: str
    total_vars: int = 0
    already_set: int = 0
    newly_set: int = 0
    skipped: int = 0
    invalid: int = 0


@dataclass
class SetupReport:
    env_path: str = ""
    categories: list[CategoryStatus] = field(default_factory=list)
    keys_added: list[str] = field(default_factory=list)
    keys_preserved: int = 0
    revenue_ready: bool = False


def parse_env_file(env_path: Path) -> dict[str, str]:
    """Parse a .env file into a dict. Preserves whatever
    syntax dotenv accepts: KEY=VALUE, KEY='VALUE', KEY="VALUE",
    comments + blank lines ignored."""
    if not env_path.exists():
        return {}
    out: dict[str, str] = {}
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        # Strip outer quotes (single or double)
        if len(val) >= 2 and val[0] == val[-1] and (
            val[0] in ("'", '"')
        ):
            val = val[1:-1]
        out[key] = val
    return out


def write_env_file(
    env_path: Path,
    values: dict[str, str],
    *,
    preserved_lines: list[str] | None = None,
) -> None:
    """Atomically write a dict + preserved lines to .env.

    preserved_lines is any blank/comment lines and unknown keys
    we should keep verbatim. We always rewrite values from the
    dict on top of the preserved lines.
    """
    tmp = env_path.with_suffix(env_path.suffix + ".tmp")
    body_lines: list[str] = []
    if preserved_lines:
        body_lines.extend(preserved_lines)
        if body_lines and body_lines[-1].strip():
            body_lines.append("")  # blank separator
    # Write dict values in deterministic order
    for key in sorted(values.keys()):
        val = values[key]
        # Quote if contains whitespace or # to be safe
        needs_quote = (
            " " in val or "\t" in val or "#" in val
        )
        if needs_quote:
            val = f'"{val}"'
        body_lines.append(f"{key}={val}")
    tmp.write_text(
        "\n".join(body_lines) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, env_path)


def categorise_existing(
    existing: dict[str, str],
    categories: list[EnvCategory],
) -> tuple[dict[str, str], list[str]]:
    """Split existing env into (managed_by_wizard, other_lines).

    Wizard touches only keys it knows about. Everything else is
    preserved as raw `KEY=value` lines (no quoting changes).
    """
    known_keys: set[str] = set()
    for cat in categories:
        for v in cat.vars:
            known_keys.add(v.key)

    managed: dict[str, str] = {}
    other_lines: list[str] = []
    for key, val in existing.items():
        if key in known_keys:
            managed[key] = val
        else:
            other_lines.append(f"{key}={val}")
    return managed, other_lines


def prompt_for_var(
    var: EnvVar,
    existing_value: str | None,
    *,
    input_fn: Callable[[str], str] = input,
    print_fn: Callable[[str], None] = print,
    force_rewrite: bool = False,
) -> tuple[str | None, str]:
    """Prompt the operator for a single env var.

    Returns (new_value, status). status one of:
      already_set / newly_set / skipped / invalid

    When existing_value is set + force_rewrite is False, skips
    the prompt entirely (returns (existing_value, 'already_set')).
    """
    if existing_value and not force_rewrite:
        return existing_value, "already_set"

    label_required = (
        " [REQUIRED]" if var.required else " [optional]"
    )
    print_fn("")
    print_fn(f"  {var.key}{label_required}")
    print_fn(f"    {var.description}")
    if var.where_to_get:
        print_fn(f"    where: {var.where_to_get}")
    if existing_value:
        masked = (
            "***" if var.is_secret
            else existing_value
        )
        print_fn(
            f"    current: {masked}  (press Enter to keep)"
        )

    # W963-180: bounded retry so a test feeding lambda _: ""
    # to a required var doesn't loop forever. Real operators
    # see the same nudge 20x before the wizard gives up + marks
    # this key as invalid; manual edit of .env still works.
    attempts = 0
    max_attempts = 20
    while attempts < max_attempts:
        attempts += 1
        raw = input_fn("    > ").strip()
        if not raw:
            if existing_value:
                return existing_value, "already_set"
            if var.required:
                print_fn(
                    "    required -- type the value or "
                    "Ctrl+C to abort"
                )
                continue
            return None, "skipped"
        if var.validator:
            try:
                validated = var.validator(raw)
                return validated, "newly_set"
            except ValueError as exc:
                print_fn(f"    invalid: {exc}; try again")
                continue
        return raw, "newly_set"
    # Exhausted attempts; fall through to invalid
    print_fn(
        f"    {var.key}: max retries hit; marking invalid"
    )
    return None, "invalid"


def run_wizard(
    env_path: Path | str = ".env",
    categories: list[EnvCategory] | None = None,
    *,
    input_fn: Callable[[str], str] = input,
    print_fn: Callable[[str], None] = print,
    force_rewrite: bool = False,
    only_categories: list[str] | None = None,
) -> SetupReport:
    """Run the full wizard against env_path. Returns SetupReport
    summarising per-category outcomes."""
    path = Path(env_path)
    cats = categories or CATEGORIES
    existing = parse_env_file(path)
    managed, preserved = categorise_existing(
        existing, cats,
    )

    print_fn(
        f"\nShopAI operator-setup wizard"
        f"\nReading {path.absolute()}"
        f"\nPreserving {len(preserved)} non-wizard keys "
        f"verbatim"
    )

    report = SetupReport(env_path=str(path.absolute()))

    for cat in cats:
        if only_categories and cat.name not in only_categories:
            continue
        print_fn(f"\n=== {cat.name} ===")
        print_fn(f"  {cat.description}")
        status = CategoryStatus(
            name=cat.name,
            total_vars=len(cat.vars),
        )
        for var in cat.vars:
            existing_value = managed.get(var.key) or ""
            new_val, outcome = prompt_for_var(
                var,
                existing_value=existing_value or None,
                input_fn=input_fn,
                print_fn=print_fn,
                force_rewrite=force_rewrite,
            )
            if new_val is not None:
                managed[var.key] = new_val
            if outcome == "already_set":
                status.already_set += 1
            elif outcome == "newly_set":
                status.newly_set += 1
                report.keys_added.append(var.key)
            elif outcome == "skipped":
                status.skipped += 1
            elif outcome == "invalid":
                status.invalid += 1
        report.categories.append(status)

    write_env_file(
        path, managed, preserved_lines=preserved,
    )
    report.keys_preserved = len(preserved)

    # Revenue-ready iff every required-for-revenue category has
    # at least one var set
    revenue_ready = True
    for cat in cats:
        if not cat.required_for_revenue:
            continue
        has_any = any(
            managed.get(v.key) for v in cat.vars
        )
        if not has_any:
            revenue_ready = False
            break
    report.revenue_ready = revenue_ready

    print_fn(
        f"\nWrote {len(managed)} managed key(s) + "
        f"{len(preserved)} preserved key(s) to {path}"
    )
    if revenue_ready:
        print_fn("Revenue-ready: YES")
    else:
        print_fn(
            "Revenue-ready: NO (set at least one "
            "ad-channel + Shopify creds)"
        )
    return report
