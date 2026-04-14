"""Cost ledger module tests — Option Z phase 1.

Unit tests for the per-caller cost attribution primitive. Focus on:

* sanitisation — garbage caller tags collapse to ``"unknown"``
* accounting — per-caller and per-row totals stay in sync
* bounded memory — runaway unique tags land in the overflow bucket
* thread safety — parallel writers don't corrupt totals
* singleton — process-wide ledger round-trips through reset/get
"""
from __future__ import annotations

import threading

import pytest

from core.adapters.cost_ledger import (
    DEFAULT_CALLER,
    OVERFLOW_CALLER,
    CostLedger,
    get_cost_ledger,
    reset_cost_ledger,
)


class _Clock:
    def __init__(self, start: float = 1000.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, s: float) -> None:
        self.t += s


class TestCallerNormalisation:
    def test_blank_collapses_to_unknown(self):
        assert CostLedger.normalise_caller(None) == DEFAULT_CALLER
        assert CostLedger.normalise_caller("") == DEFAULT_CALLER
        assert CostLedger.normalise_caller("   ") == DEFAULT_CALLER

    def test_lowercases(self):
        assert CostLedger.normalise_caller("SupportAgent") == "supportagent"

    def test_allows_safe_punctuation(self):
        assert CostLedger.normalise_caller("ops.reflection_hook/v2") == (
            "ops.reflection_hook/v2"
        )

    def test_rejects_spaces_and_specials(self):
        assert CostLedger.normalise_caller("support agent") == DEFAULT_CALLER
        assert CostLedger.normalise_caller("bad;drop") == DEFAULT_CALLER
        assert CostLedger.normalise_caller("x" * 65) == DEFAULT_CALLER


class TestRecord:
    def test_records_single_row(self):
        lg = CostLedger(clock=_Clock())
        lg.record(
            caller="agent", adapter="openai", capability="chat_complete",
            usd=0.01, tokens_in=100, tokens_out=20,
        )
        rows = lg.rows()
        assert len(rows) == 1
        assert rows[0]["total_usd"] == 0.01
        assert rows[0]["calls"] == 1
        assert rows[0]["tokens_in"] == 100
        assert rows[0]["caller"] == "agent"

    def test_accumulates_same_key(self):
        lg = CostLedger(clock=_Clock())
        for _ in range(3):
            lg.record(
                caller="agent", adapter="openai",
                capability="chat_complete", usd=0.01,
            )
        rows = lg.rows()
        assert len(rows) == 1
        assert rows[0]["total_usd"] == pytest.approx(0.03)
        assert rows[0]["calls"] == 3

    def test_splits_by_caller_adapter_capability(self):
        lg = CostLedger(clock=_Clock())
        lg.record(caller="a", adapter="openai", capability="chat_complete", usd=0.01)
        lg.record(caller="b", adapter="openai", capability="chat_complete", usd=0.02)
        lg.record(caller="a", adapter="anthropic", capability="chat_complete", usd=0.03)
        lg.record(caller="a", adapter="openai", capability="embed_text", usd=0.04)
        assert len(lg.rows()) == 4
        assert lg.total_usd() == pytest.approx(0.10)

    def test_ignores_zero_and_negative_cost(self):
        lg = CostLedger(clock=_Clock())
        lg.record(caller="a", adapter="x", capability="y", usd=0.0)
        lg.record(caller="a", adapter="x", capability="y", usd=-1.0)
        assert lg.rows() == []

    def test_normalises_caller_on_write(self):
        lg = CostLedger(clock=_Clock())
        lg.record(caller="Bad Caller!", adapter="x", capability="y", usd=0.01)
        lg.record(caller=None, adapter="x", capability="y", usd=0.02)
        rows = lg.rows()
        # Both should collapse to "unknown" and merge into one row.
        assert len(rows) == 1
        assert rows[0]["caller"] == DEFAULT_CALLER
        assert rows[0]["total_usd"] == pytest.approx(0.03)

    def test_timestamps_first_and_last_seen(self):
        clk = _Clock(1000.0)
        lg = CostLedger(clock=clk)
        lg.record(caller="a", adapter="x", capability="y", usd=0.01)
        clk.advance(30.0)
        lg.record(caller="a", adapter="x", capability="y", usd=0.01)
        row = lg.rows()[0]
        assert row["first_seen"] == 1000.0
        assert row["last_seen"] == 1030.0

    def test_record_never_raises_on_bad_input(self):
        lg = CostLedger(clock=_Clock())
        # None / empty adapter / capability should be coerced, not raise.
        lg.record(caller="a", adapter="", capability="", usd=0.01)
        rows = lg.rows()
        assert rows[0]["adapter"] == "unknown"
        assert rows[0]["capability"] == "unknown"


class TestPerCaller:
    def test_rolls_up_to_one_row_per_caller(self):
        lg = CostLedger(clock=_Clock())
        lg.record(caller="a", adapter="openai", capability="c1", usd=0.01)
        lg.record(caller="a", adapter="anthropic", capability="c2", usd=0.02)
        lg.record(caller="b", adapter="openai", capability="c1", usd=0.05)
        per = lg.per_caller()
        assert len(per) == 2
        # Sorted by total desc.
        assert per[0]["caller"] == "b"
        assert per[0]["total_usd"] == pytest.approx(0.05)
        a = [r for r in per if r["caller"] == "a"][0]
        assert a["total_usd"] == pytest.approx(0.03)
        assert a["adapter_count"] == 2
        assert a["capability_count"] == 2


class TestSnapshot:
    def test_empty_snapshot_is_well_formed(self):
        lg = CostLedger(clock=_Clock())
        snap = lg.snapshot()
        assert snap["total_usd"] == 0.0
        assert snap["rows"] == []
        assert snap["per_caller"] == []
        assert snap["key_count"] == 0
        assert snap["overflow"]["active"] is False

    def test_snapshot_exposes_totals_and_rows(self):
        lg = CostLedger(clock=_Clock())
        lg.record(caller="a", adapter="openai", capability="c", usd=0.10)
        lg.record(caller="b", adapter="openai", capability="c", usd=0.05)
        snap = lg.snapshot()
        assert snap["total_usd"] == pytest.approx(0.15)
        assert len(snap["rows"]) == 2
        assert len(snap["per_caller"]) == 2
        # Rows sorted desc by spend.
        assert snap["rows"][0]["caller"] == "a"


class TestOverflow:
    def test_overflow_folds_into_one_bucket(self):
        lg = CostLedger(max_keys=3, clock=_Clock())
        for i in range(10):
            lg.record(
                caller=f"c{i}", adapter="openai", capability="chat_complete",
                usd=0.001,
            )
        snap = lg.snapshot()
        assert snap["key_count"] == 3
        assert snap["overflow"]["active"] is True
        assert snap["overflow"]["calls"] == 7
        assert snap["overflow"]["usd"] == pytest.approx(0.007)
        # Total still reflects every dollar recorded.
        assert snap["total_usd"] == pytest.approx(0.010)

    def test_overflow_inactive_below_cap(self):
        lg = CostLedger(max_keys=5, clock=_Clock())
        for i in range(3):
            lg.record(
                caller=f"c{i}", adapter="x", capability="y", usd=0.01,
            )
        assert lg.snapshot()["overflow"]["active"] is False


class TestReset:
    def test_reset_forgets_everything(self):
        lg = CostLedger(clock=_Clock())
        lg.record(caller="a", adapter="x", capability="y", usd=0.01)
        lg.reset()
        assert lg.total_usd() == 0.0
        assert lg.rows() == []


class TestConstructorValidation:
    def test_max_keys_must_be_positive(self):
        with pytest.raises(ValueError):
            CostLedger(max_keys=0)
        with pytest.raises(ValueError):
            CostLedger(max_keys=-5)


class TestSingleton:
    def test_get_returns_same_instance(self):
        reset_cost_ledger()
        a = get_cost_ledger()
        b = get_cost_ledger()
        assert a is b

    def test_reset_swaps_instance(self):
        reset_cost_ledger()
        a = get_cost_ledger()
        reset_cost_ledger()
        b = get_cost_ledger()
        assert a is not b


class TestThreadSafety:
    def test_parallel_writers_do_not_lose_records(self):
        lg = CostLedger(clock=_Clock())
        threads = []
        per_thread = 100

        def writer(tid: int) -> None:
            for _ in range(per_thread):
                lg.record(
                    caller=f"t{tid}", adapter="openai",
                    capability="chat_complete", usd=0.001,
                )

        for tid in range(10):
            t = threading.Thread(target=writer, args=(tid,))
            threads.append(t)
            t.start()
        for t in threads:
            t.join()

        snap = lg.snapshot()
        # 10 threads × 100 calls = 1000 calls, $1.00 total.
        assert snap["key_count"] == 10
        assert snap["total_usd"] == pytest.approx(1.00)
        total_calls = sum(r["calls"] for r in snap["rows"])
        assert total_calls == 10 * per_thread


class TestOverflowConstant:
    def test_overflow_caller_constant_exposed(self):
        # Dashboard & tests reference this constant; lock the spelling.
        assert OVERFLOW_CALLER == "__overflow__"
