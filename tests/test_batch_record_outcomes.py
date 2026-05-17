"""Tests for ``scripts/batch_record_outcomes.py``.

Standalone script for CSV-driven bulk outcome backfill.
Tests cover:
  - CSV parsing: required columns, polarity validation, revenue
    coercion, defaults for optional columns
  - Execution: happy path, unknown action skip, queue raise,
    record_outcome returning False
  - Dry-run: no record_outcome calls
"""
from __future__ import annotations

import importlib.util
from unittest.mock import MagicMock, patch

import pytest


def _load_script():
    import sys
    spec = importlib.util.spec_from_file_location(
        "batch_record_outcomes",
        "scripts/batch_record_outcomes.py",
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    # Register before exec_module so ``@dataclass`` can look up
    # the module via its ``__module__`` attribute.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def mod():
    return _load_script()


def _write_csv(tmp_path, content: str):
    path = tmp_path / "outcomes.csv"
    path.write_text(content, encoding="utf-8")
    return str(path)


# ─── CSV parsing ─────────────────────────────────────────────


class TestCsvParsing:

    def test_minimal_required_columns(self, mod, tmp_path):
        csv_path = _write_csv(
            tmp_path,
            "action_id,polarity\nappr_1,positive\n",
        )
        rows, errors = mod._parse_csv(csv_path)
        assert errors == []
        assert len(rows) == 1
        assert rows[0].action_id == "appr_1"
        assert rows[0].polarity == "positive"
        # Defaults
        assert rows[0].revenue == 0.0
        assert rows[0].topic == "manual"
        assert rows[0].source_event == "backfill"

    def test_full_columns(self, mod, tmp_path):
        csv_path = _write_csv(
            tmp_path,
            "action_id,polarity,revenue,topic,source_event\n"
            "appr_1,positive,42.5,orders/create,ops-1\n",
        )
        rows, errors = mod._parse_csv(csv_path)
        assert errors == []
        assert rows[0].revenue == 42.5
        assert rows[0].topic == "orders/create"
        assert rows[0].source_event == "ops-1"

    def test_missing_required_column_fails(self, mod, tmp_path):
        # No polarity column.
        csv_path = _write_csv(
            tmp_path, "action_id,revenue\nappr_1,42\n",
        )
        rows, errors = mod._parse_csv(csv_path)
        assert rows == []
        assert len(errors) == 1
        assert "polarity" in errors[0]

    def test_invalid_polarity_rejected_with_row_num(
        self, mod, tmp_path,
    ):
        csv_path = _write_csv(
            tmp_path,
            "action_id,polarity\n"
            "appr_1,positive\n"
            "appr_2,maybe\n"
            "appr_3,negative\n",
        )
        rows, errors = mod._parse_csv(csv_path)
        # Rows 1 + 3 valid; row 2 errored.
        assert len(rows) == 2
        assert {r.action_id for r in rows} == {"appr_1", "appr_3"}
        assert len(errors) == 1
        assert "polarity" in errors[0]
        assert "maybe" in errors[0]

    def test_empty_action_id_rejected(self, mod, tmp_path):
        csv_path = _write_csv(
            tmp_path,
            "action_id,polarity\n,positive\nappr_1,positive\n",
        )
        rows, errors = mod._parse_csv(csv_path)
        assert len(rows) == 1
        assert len(errors) == 1
        assert "action_id is empty" in errors[0]

    def test_non_numeric_revenue_rejected(self, mod, tmp_path):
        csv_path = _write_csv(
            tmp_path,
            "action_id,polarity,revenue\n"
            "appr_1,positive,not_a_number\n",
        )
        rows, errors = mod._parse_csv(csv_path)
        assert len(rows) == 0
        assert len(errors) == 1
        assert "not numeric" in errors[0]

    def test_polarity_case_normalised(self, mod, tmp_path):
        """Operator typos like ``Positive`` shouldn't reject;
        normalize to lowercase before validation."""
        csv_path = _write_csv(
            tmp_path,
            "action_id,polarity\nappr_1,Positive\n",
        )
        rows, errors = mod._parse_csv(csv_path)
        assert errors == []
        assert rows[0].polarity == "positive"

    def test_missing_file_returns_error(self, mod, tmp_path):
        rows, errors = mod._parse_csv(
            str(tmp_path / "does-not-exist.csv"),
        )
        assert rows == []
        assert any("not found" in e for e in errors)

    def test_no_header_returns_error(self, mod, tmp_path):
        path = tmp_path / "empty.csv"
        path.write_text("", encoding="utf-8")
        rows, errors = mod._parse_csv(str(path))
        assert rows == []
        # csv.DictReader returns None fieldnames for empty input.
        assert len(errors) >= 1


# ─── Execution ───────────────────────────────────────────────


def _make_row(mod, **kw):
    """Build a _Row helper for execution tests."""
    defaults = dict(
        row_num=2, action_id="appr_x", polarity="positive",
        revenue=0.0, topic="manual", source_event="backfill",
    )
    defaults.update(kw)
    return mod._Row(**defaults)


class TestExecution:

    def test_happy_path_records_each_row(self, mod):
        q = MagicMock()
        action = MagicMock(id="appr_x")
        q.get.return_value = action
        q.record_outcome.return_value = True

        rows = [
            _make_row(mod, row_num=2, action_id="appr_1"),
            _make_row(
                mod, row_num=3, action_id="appr_2",
                polarity="negative", revenue=-10.0,
            ),
        ]
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            summary = mod._record(rows, dry_run=False)
        assert summary["ok"] == 2
        assert summary["failed"] == 0
        assert summary["skipped"] == 0
        assert summary["errors"] == []
        # Two record_outcome calls with expected polarities.
        assert q.record_outcome.call_count == 2
        polarities = [
            call.kwargs["polarity"]
            for call in q.record_outcome.call_args_list
        ]
        assert polarities == ["positive", "negative"]

    def test_unknown_action_is_skipped(self, mod):
        q = MagicMock()
        # get() returns None for unknown ids.
        q.get.return_value = None
        rows = [_make_row(mod, action_id="appr_ghost")]
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            summary = mod._record(rows, dry_run=False)
        assert summary["ok"] == 0
        assert summary["skipped"] == 1
        # record_outcome should NOT be called for missing action.
        q.record_outcome.assert_not_called()

    def test_record_outcome_raise_counted_as_failed(self, mod):
        q = MagicMock()
        q.get.return_value = MagicMock()
        q.record_outcome.side_effect = RuntimeError("db locked")
        rows = [_make_row(mod, action_id="appr_x")]
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            summary = mod._record(rows, dry_run=False)
        assert summary["ok"] == 0
        assert summary["failed"] == 1
        assert any("db locked" in e for e in summary["errors"])

    def test_record_outcome_returns_false_counted_as_failed(
        self, mod,
    ):
        q = MagicMock()
        q.get.return_value = MagicMock()
        q.record_outcome.return_value = False
        rows = [_make_row(mod, action_id="appr_x")]
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            summary = mod._record(rows, dry_run=False)
        assert summary["failed"] == 1

    def test_dry_run_skips_record_outcome(self, mod):
        """Dry-run validates each action exists but doesn't
        write."""
        q = MagicMock()
        q.get.return_value = MagicMock()
        rows = [
            _make_row(mod, action_id="appr_1"),
            _make_row(mod, action_id="appr_2"),
        ]
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            summary = mod._record(rows, dry_run=True)
        assert summary["ok"] == 2
        # record_outcome NOT called under --dry-run.
        q.record_outcome.assert_not_called()

    def test_metrics_carry_batch_source_marker(self, mod):
        """Every recorded outcome should be tagged with
        ``manually_recorded=True`` and a ``batch_source``
        marker so downstream queries can filter them."""
        q = MagicMock()
        q.get.return_value = MagicMock()
        q.record_outcome.return_value = True
        rows = [_make_row(mod, action_id="appr_x", revenue=42.0)]
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            mod._record(rows, dry_run=False)
        metrics = q.record_outcome.call_args.kwargs["metrics"]
        assert metrics["manually_recorded"] is True
        assert "batch_source" in metrics
        assert "batch_record_outcomes" in metrics["batch_source"]
        # Non-zero revenue surfaces; zero would have been omitted.
        assert metrics["revenue"] == 42.0

    def test_zero_revenue_omitted_from_metrics(self, mod):
        q = MagicMock()
        q.get.return_value = MagicMock()
        q.record_outcome.return_value = True
        rows = [_make_row(mod, action_id="appr_x", revenue=0.0)]
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            mod._record(rows, dry_run=False)
        metrics = q.record_outcome.call_args.kwargs["metrics"]
        assert "revenue" not in metrics
        # Still tagged.
        assert metrics["manually_recorded"] is True
