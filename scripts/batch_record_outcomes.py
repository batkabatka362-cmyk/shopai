"""Bulk record outcomes on executed actions from a CSV file.

Operational tool for backfilling outcomes when Shopify webhooks
were unavailable, queue backlog dropped events, or the operator
needs to retroactively attribute revenue across many actions.

Each CSV row maps to a single ``queue.record_outcome(...)`` call
-- the same path the webhook-driven recorder uses, so the AGI
signal (DecisionRetrieval + MemoryIntelligence) sees the
manually-recorded outcomes identically.

Usage:
    python scripts/batch_record_outcomes.py outcomes.csv
    python scripts/batch_record_outcomes.py outcomes.csv --dry-run

CSV format (header row required):

    action_id,polarity,revenue,topic,source_event
    appr_1779011988196_09728cbb,positive,50.0,orders/create,backfill
    appr_1779012001100_aabbccdd,negative,-15.0,refunds/create,backfill

Required columns: ``action_id``, ``polarity``.
Optional columns: ``revenue`` (default 0), ``topic`` (default
``manual``), ``source_event`` (default ``backfill``).

Safety:
- Verifies each action exists before recording. Unknown ids are
  reported as errors and skipped; the run continues for the
  remaining rows.
- ``record_outcome`` is the canonical API -- it's idempotent at
  the SQL layer for the same (action_id, topic, polarity,
  recorded_at) tuple as far as the queue's deduplication
  decides. This script doesn't add its own deduplication.
- ``--dry-run`` validates the entire CSV without writing.
- All metrics dicts get ``manually_recorded: True`` + a
  ``batch_source`` field so downstream queries can filter
  these out of automated reports if needed.

Exit codes:
- 0: every row recorded successfully (or dry-run validation passed)
- 1: at least one row failed (missing action, bad polarity,
     queue raise). Summary printed to stderr.
- 2: CSV malformed / file not found / no header
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from dataclasses import dataclass

# Allow running as ``python scripts/batch_record_outcomes.py``
# from the repo root without an editable install.
_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)),
)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


_REQUIRED_COLS = ("action_id", "polarity")
_VALID_POLARITIES = {"positive", "negative", "neutral"}


@dataclass(frozen=True)
class _Row:
    """One parsed CSV row, normalized."""

    row_num: int  # 1-based, matching the spreadsheet view (header=1)
    action_id: str
    polarity: str
    revenue: float
    topic: str
    source_event: str


def _parse_csv(path: str) -> tuple[list[_Row], list[str]]:
    """Read + validate the CSV. Returns (rows, errors).

    Errors are operator-friendly strings tagged with row numbers
    so the operator can fix the source spreadsheet.
    """
    rows: list[_Row] = []
    errors: list[str] = []
    try:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                return [], ["CSV has no header row"]
            missing = [
                c for c in _REQUIRED_COLS
                if c not in reader.fieldnames
            ]
            if missing:
                return [], [
                    f"CSV missing required column(s): {missing}"
                ]
            for raw in reader:
                # csv.DictReader reports zero-based positions
                # via ``reader.line_num`` which counts header
                # lines too -- subtract 1 for "user view".
                row_num = reader.line_num
                action_id = (raw.get("action_id") or "").strip()
                polarity = (raw.get("polarity") or "").strip().lower()
                if not action_id:
                    errors.append(
                        f"row {row_num}: action_id is empty",
                    )
                    continue
                if polarity not in _VALID_POLARITIES:
                    errors.append(
                        f"row {row_num}: polarity {polarity!r} not "
                        f"in {sorted(_VALID_POLARITIES)}",
                    )
                    continue
                revenue_raw = (
                    raw.get("revenue") or ""
                ).strip()
                if revenue_raw:
                    try:
                        revenue = float(revenue_raw)
                    except ValueError:
                        errors.append(
                            f"row {row_num}: revenue {revenue_raw!r} "
                            "is not numeric",
                        )
                        continue
                else:
                    revenue = 0.0
                topic = (raw.get("topic") or "manual").strip() or "manual"
                source_event = (
                    raw.get("source_event") or "backfill"
                ).strip() or "backfill"
                rows.append(_Row(
                    row_num=row_num,
                    action_id=action_id,
                    polarity=polarity,
                    revenue=revenue,
                    topic=topic,
                    source_event=source_event,
                ))
    except FileNotFoundError:
        return [], [f"file not found: {path}"]
    except OSError as exc:
        return [], [f"could not read {path}: {exc}"]
    return rows, errors


def _record(rows: list[_Row], *, dry_run: bool) -> dict:
    """Execute the batch. Returns a summary dict."""
    from core.approval.queue import get_approval_queue

    queue = get_approval_queue()

    ok_count = 0
    skip_count = 0
    fail_count = 0
    errors: list[str] = []

    for r in rows:
        try:
            action = queue.get(r.action_id)
        except Exception as exc:  # noqa: BLE001
            errors.append(
                f"row {r.row_num}: lookup for {r.action_id!r} "
                f"raised: {exc}",
            )
            fail_count += 1
            continue
        if action is None:
            errors.append(
                f"row {r.row_num}: action {r.action_id!r} not found",
            )
            skip_count += 1
            continue

        if dry_run:
            ok_count += 1
            continue

        metrics: dict = {
            "manually_recorded": True,
            "batch_source": "scripts/batch_record_outcomes",
        }
        if r.revenue != 0.0:
            metrics["revenue"] = r.revenue

        try:
            recorded = queue.record_outcome(
                r.action_id,
                topic=r.topic,
                polarity=r.polarity,
                metrics=metrics,
                source_event=r.source_event,
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(
                f"row {r.row_num}: record_outcome raised: {exc}",
            )
            fail_count += 1
            continue
        if not recorded:
            errors.append(
                f"row {r.row_num}: record_outcome returned falsy "
                f"for {r.action_id!r} (action may not be executed)",
            )
            fail_count += 1
            continue
        ok_count += 1

    return {
        "ok": ok_count,
        "skipped": skip_count,
        "failed": fail_count,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Bulk record outcomes on executed actions from CSV."
        ),
    )
    parser.add_argument("csv_path", help="Path to outcomes CSV")
    parser.add_argument(
        "--dry-run", action="store_true",
        help=(
            "Validate the CSV + verify each action exists, "
            "but don't call record_outcome."
        ),
    )
    args = parser.parse_args()

    rows, parse_errors = _parse_csv(args.csv_path)
    if parse_errors:
        for e in parse_errors:
            print(f"Error: {e}", file=sys.stderr)
        return 2

    if not rows:
        print("CSV had no data rows.", file=sys.stderr)
        return 2

    label = "Dry-run: validating" if args.dry_run else "Recording"
    print(f"{label} {len(rows)} outcome(s) from {args.csv_path}")
    summary = _record(rows, dry_run=args.dry_run)

    print()
    print(
        f"  OK:      {summary['ok']:>4d}\n"
        f"  Skipped: {summary['skipped']:>4d}\n"
        f"  Failed:  {summary['failed']:>4d}"
    )
    if summary["errors"]:
        print()
        print("Errors:", file=sys.stderr)
        for e in summary["errors"]:
            print(f"  - {e}", file=sys.stderr)

    if summary["failed"] > 0 or summary["skipped"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
