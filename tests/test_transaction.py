"""Transaction layer — retry / idempotency / rollback tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.execution import transaction as tx


class TestSingleStepHappy(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = tx._STORE
        tx._STORE = Path(self._tmp.name) / "tx.json"

    def tearDown(self) -> None:
        tx._STORE = self._orig
        self._tmp.cleanup()

    def test_succeeds_on_first_call(self) -> None:
        t = tx.Transaction("t1")
        result = t.run(step="x", op=lambda: 42)
        self.assertEqual(result, 42)
        self.assertEqual(t._record.steps[0].status, "succeeded")


class TestRetries(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = tx._STORE
        tx._STORE = Path(self._tmp.name) / "tx.json"

    def tearDown(self) -> None:
        tx._STORE = self._orig
        self._tmp.cleanup()

    def test_retries_on_retriable_error(self) -> None:
        calls = {"n": 0}
        def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise tx.RetriableError("transient")
            return "ok"
        t = tx.Transaction("t2", max_retries=4, initial_backoff_s=0.0)
        result = t.run(step="x", op=flaky)
        self.assertEqual(result, "ok")
        self.assertEqual(calls["n"], 3)

    def test_non_retriable_short_circuits(self) -> None:
        calls = {"n": 0}
        def broken():
            calls["n"] += 1
            raise ValueError("hard fail")
        t = tx.Transaction("t3", max_retries=4, initial_backoff_s=0.0)
        with self.assertRaises(ValueError):
            t.run(step="x", op=broken)
        self.assertEqual(calls["n"], 1)

    def test_exceeds_retries_raises(self) -> None:
        def always_flaky():
            raise tx.RetriableError("perma")
        t = tx.Transaction("t4", max_retries=3, initial_backoff_s=0.0)
        with self.assertRaises(tx.RetriableError):
            t.run(step="x", op=always_flaky)


class TestIdempotency(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = tx._STORE
        tx._STORE = Path(self._tmp.name) / "tx.json"

    def tearDown(self) -> None:
        tx._STORE = self._orig
        self._tmp.cleanup()

    def test_cached_result_skips_op(self) -> None:
        calls = {"n": 0}
        def op():
            calls["n"] += 1
            return {"product_id": 123}
        # First tx — op runs
        with tx.Transaction("a") as t1:
            t1.run(step="create", op=op, idempotency_key="K")
        # Second tx — cached hit, op not called
        with tx.Transaction("b") as t2:
            result = t2.run(step="create", op=op, idempotency_key="K")
        self.assertEqual(calls["n"], 1)
        self.assertEqual(result["product_id"], 123)


class TestRollback(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = tx._STORE
        tx._STORE = Path(self._tmp.name) / "tx.json"

    def tearDown(self) -> None:
        tx._STORE = self._orig
        self._tmp.cleanup()

    def test_rollback_fires_in_reverse(self) -> None:
        compensated: list[str] = []
        def comp_a(result): compensated.append(f"a:{result}")
        def comp_b(result): compensated.append(f"b:{result}")
        def failing_c(): raise ValueError("boom")

        try:
            with tx.Transaction("t5") as t:
                t.run(step="a", op=lambda: 1, compensate=comp_a)
                t.run(step="b", op=lambda: 2, compensate=comp_b)
                t.run(step="c", op=failing_c)
        except ValueError:
            pass

        # Compensations run in reverse order: b then a
        self.assertEqual(compensated, ["b:2", "a:1"])

    def test_compensation_failure_marked_but_does_not_abort(self) -> None:
        comps: list[str] = []
        def comp_a(result):
            raise RuntimeError("cannot compensate")
        def comp_b(result): comps.append("b")
        def fail(): raise ValueError("x")

        try:
            with tx.Transaction("t6") as t:
                t.run(step="a", op=lambda: 1, compensate=comp_a)
                t.run(step="b", op=lambda: 2, compensate=comp_b)
                t.run(step="c", op=fail)
        except ValueError:
            pass
        # b still rolled back
        self.assertEqual(comps, ["b"])
        # a marked failed_rollback
        a_record = next(r for r in t._record.steps if r.step == "a")
        self.assertEqual(a_record.status, "failed_rollback")


class TestCommit(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = tx._STORE
        tx._STORE = Path(self._tmp.name) / "tx.json"

    def tearDown(self) -> None:
        tx._STORE = self._orig
        self._tmp.cleanup()

    def test_commit_on_happy_path(self) -> None:
        with tx.Transaction("t_happy") as t:
            t.run(step="x", op=lambda: "done")
        record = tx.get_transaction("t_happy")
        self.assertEqual(record["status"], "committed")


if __name__ == "__main__":
    unittest.main()
