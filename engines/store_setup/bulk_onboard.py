"""Wave 99: bulk onboarding wrapper.

The Wave 92-98 ``shopai onboard`` handles one store. Empire-scale
operators with 20+ stores need a bulk wrapper. This module reads
a CSV of store rows + runs ``onboard_store()`` on each, then
aggregates the results into a single empire-wide report.

## CSV format

Required columns:
  - ``store_id``  -- stable identifier
  - ``shop_url``  -- Shopify domain

Optional columns (any subset, missing -> empty string default):
  - ``api_key``        -- legacy token (mutually exclusive with
                          client_id/client_secret)
  - ``client_id``      -- OAuth client id
  - ``client_secret``  -- OAuth secret
  - ``name``           -- human-readable name
  - ``niche``          -- pre-set niche (skips detection)
  - ``store_type``     -- dropshipping / brand / niche / general

Header row required. Empty lines + lines starting with ``#`` are
skipped.

## Failure semantics

Each store is independent -- one row's failure doesn't poison
the rest. The bulk wrapper continues through every row + returns
an aggregate report.

When ``max_failures`` > 0 and the failure count exceeds it, the
wrapper stops AT THAT ROW and returns a partial report (with
``stopped_early=True``). Useful for cron-driven bulk runs that
should bail on systemic problems (auth keys all expired, etc.)
rather than silently flapping through 20 failed onboardings.
"""
from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from engines.store_setup.onboarding_wizard import (
    OnboardingResult,
    onboard_store,
)

logger = logging.getLogger(__name__)

# CSV columns the wrapper knows about. Anything else is ignored
# (so callers can include operator-only columns like email).
_KNOWN_COLUMNS: frozenset[str] = frozenset({
    "store_id", "shop_url",
    "api_key", "client_id", "client_secret",
    "name", "niche", "store_type",
})

_REQUIRED_COLUMNS: frozenset[str] = frozenset({
    "store_id", "shop_url",
})


@dataclass
class BulkOnboardRow:
    """One row's input + result."""
    row_index: int
    store_id: str
    shop_url: str
    result: OnboardingResult | None = None
    skip_reason: str = ""

    @property
    def status(self) -> str:
        if self.skip_reason:
            return "skipped"
        if self.result is None:
            return "skipped"
        return self.result.final_verdict


@dataclass
class BulkOnboardReport:
    csv_path: str
    rows: list[BulkOnboardRow] = field(default_factory=list)
    stopped_early: bool = False
    error: str = ""

    @property
    def total_rows(self) -> int:
        return len(self.rows)

    @property
    def status_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for r in self.rows:
            counts[r.status] = counts.get(r.status, 0) + 1
        return counts

    @property
    def ready_count(self) -> int:
        return sum(
            1 for r in self.rows
            if r.status == "ready"
        )

    @property
    def failed_count(self) -> int:
        return sum(
            1 for r in self.rows
            if r.status == "failed"
        )


def _parse_csv(csv_path: str) -> tuple[
    list[dict[str, str]], str,
]:
    """Read the CSV + return (rows, error_message).

    Rows are returned as dicts keyed by column name (only the
    known columns). Empty / comment lines are skipped.

    On error returns ``([], "...")``.
    """
    p = Path(csv_path)
    if not p.exists():
        return [], f"file not found: {csv_path}"
    if not p.is_file():
        return [], f"not a file: {csv_path}"
    try:
        with p.open(
            "r", encoding="utf-8", newline="",
        ) as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return [], "empty CSV (no header)"
            header = set(reader.fieldnames)
            missing = _REQUIRED_COLUMNS - header
            if missing:
                return [], (
                    f"missing required column(s): "
                    f"{sorted(missing)}"
                )
            rows: list[dict[str, str]] = []
            for raw in reader:
                # Strip + skip comment / empty rows
                sid = (raw.get("store_id") or "").strip()
                if not sid or sid.startswith("#"):
                    continue
                clean: dict[str, str] = {}
                for col in _KNOWN_COLUMNS:
                    val = raw.get(col) or ""
                    clean[col] = (
                        val.strip() if isinstance(val, str)
                        else ""
                    )
                rows.append(clean)
            return rows, ""
    except Exception as exc:  # noqa: BLE001
        return [], f"CSV read failed: {exc}"


def bulk_onboard(
    csv_path: str,
    *,
    dry_run: bool = False,
    max_failures: int = 0,
    store_manager: Any = None,
) -> BulkOnboardReport:
    """Run the onboarding wizard for every row in the CSV.

    Args:
        csv_path: Path to the CSV file.
        dry_run: When True, calls onboard_store(dry_run=True)
            for every row -- no DB writes, no Shopify calls.
        max_failures: When > 0, stops processing after this many
            rows reach final_verdict="failed". 0 (default) =
            process all rows regardless.
        store_manager: Optional StoreManager override (tests).

    Returns:
        BulkOnboardReport with per-row results + aggregates.
    """
    report = BulkOnboardReport(csv_path=csv_path)
    parsed, err = _parse_csv(csv_path)
    if err:
        report.error = err
        return report
    if not parsed:
        report.error = "no usable rows in CSV"
        return report

    failures = 0
    for i, row in enumerate(parsed, start=1):
        store_id = row["store_id"]
        shop_url = row["shop_url"]
        bulk_row = BulkOnboardRow(
            row_index=i,
            store_id=store_id,
            shop_url=shop_url,
        )
        # Per-row validation: skip rows with no creds rather
        # than letting onboard_store fail-fast (the bulk view
        # surfaces it as "skipped" + a clear reason).
        api_key = row.get("api_key", "")
        cid = row.get("client_id", "")
        cs = row.get("client_secret", "")
        if not (api_key or (cid and cs)):
            bulk_row.skip_reason = (
                "no credentials (need api_key OR "
                "client_id+client_secret)"
            )
            report.rows.append(bulk_row)
            continue

        try:
            res = onboard_store(
                store_id=store_id,
                shop_url=shop_url,
                api_key=api_key,
                client_id=cid,
                client_secret=cs,
                name=row.get("name", "") or "",
                niche=row.get("niche", "") or "",
                store_type=(
                    row.get("store_type", "")
                    or "dropshipping"
                ),
                dry_run=dry_run,
                store_manager=store_manager,
            )
            bulk_row.result = res
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "bulk onboard row %d raised: %s", i, exc,
            )
            bulk_row.skip_reason = (
                f"wizard raised: {exc}"
            )

        report.rows.append(bulk_row)

        if (
            bulk_row.status == "failed"
            and max_failures > 0
        ):
            failures += 1
            if failures >= max_failures:
                report.stopped_early = True
                break

    return report
