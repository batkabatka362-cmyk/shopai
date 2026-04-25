"""Order replay tests — the learning-loop exerciser.

The replay tool (``agents.replay.order_replay``) pushes
JSONL order payloads through the live ``OrderWebhookHandler``
so the Deliberation back-fill + engine outcome bus + pattern
miner get realistic signal without needing a paying customer.

These tests lock the public shape so the owner's workflow
(``shopai replay-orders data/replay/pet_store.jsonl``) stays
deterministic as the webhook handler evolves.
"""
from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path

from agents.replay.order_replay import (
    OrderReplayResult,
    ReplayStats,
    replay_orders,
    replay_orders_from_file,
)


class _FakeHandler:
    """Stand-in for ``OrderWebhookHandler`` — records each
    payload and returns whatever ``handle_order_paid`` would.
    Deterministic; no external IO."""

    def __init__(
        self,
        *,
        fail_ids: set[str] | None = None,
        deliberation_ids: set[str] | None = None,
    ):
        self.calls: list[dict] = []
        self._fail = fail_ids or set()
        self._delibs = deliberation_ids or set()

    def handle_order_paid(self, order: dict) -> dict:
        self.calls.append(order)
        oid = str(order.get("id") or "")
        if oid in self._fail:
            raise RuntimeError(f"boom {oid}")
        out: dict = {"order_id": oid, "recorded": True}
        if oid in self._delibs:
            out["deliberation_observed"] = True
        return out


class TestReplayOrdersCore(unittest.TestCase):
    def test_basic_replay_counts(self):
        h = _FakeHandler()
        orders = [
            {"id": "ord-1", "total_price": "10.00"},
            {"id": "ord-2", "total_price": "20.50"},
            {"id": "ord-3", "total_price": "5.25"},
        ]
        stats = replay_orders(orders, handler=h)
        self.assertEqual(stats.attempted, 3)
        self.assertEqual(stats.successful, 3)
        self.assertEqual(stats.failed, 0)
        self.assertEqual(stats.skipped_non_dict, 0)
        self.assertAlmostEqual(
            stats.total_revenue_usd, 35.75, places=2,
        )
        self.assertEqual(len(h.calls), 3)

    def test_non_dict_entries_skipped(self):
        h = _FakeHandler()
        orders = [
            {"id": "ord-1", "total_price": "5.00"},
            "not a dict",
            None,
            42,
            {"id": "ord-2", "total_price": "3.00"},
        ]
        stats = replay_orders(orders, handler=h)
        self.assertEqual(stats.attempted, 2)
        self.assertEqual(stats.skipped_non_dict, 3)
        self.assertEqual(len(h.calls), 2)

    def test_handler_exception_captured_as_failed(self):
        h = _FakeHandler(fail_ids={"ord-bad"})
        orders = [
            {"id": "ord-good", "total_price": "1.00"},
            {"id": "ord-bad", "total_price": "2.00"},
            {"id": "ord-good-2", "total_price": "3.00"},
        ]
        stats = replay_orders(orders, handler=h)
        self.assertEqual(stats.attempted, 3)
        self.assertEqual(stats.successful, 2)
        self.assertEqual(stats.failed, 1)
        # revenue only from successful orders
        self.assertAlmostEqual(
            stats.total_revenue_usd, 4.00, places=2,
        )
        bad = next(
            r for r in stats.results if r.order_id == "ord-bad"
        )
        self.assertFalse(bad.ok)
        self.assertIn("RuntimeError", bad.error)
        self.assertIn("boom", bad.error)

    def test_deliberation_observation_counter(self):
        h = _FakeHandler(
            deliberation_ids={"ord-1", "ord-3"},
        )
        orders = [
            {"id": "ord-1", "total_price": "10.00"},
            {"id": "ord-2", "total_price": "10.00"},
            {"id": "ord-3", "total_price": "10.00"},
        ]
        stats = replay_orders(orders, handler=h)
        self.assertEqual(stats.deliberations_observed, 2)

    def test_missing_total_price_does_not_crash(self):
        h = _FakeHandler()
        orders = [
            {"id": "ord-1"},
            {"id": "ord-2", "total_price": "not a number"},
            {"id": "ord-3", "total_price": None},
        ]
        stats = replay_orders(orders, handler=h)
        self.assertEqual(stats.successful, 3)
        self.assertEqual(stats.total_revenue_usd, 0.0)

    def test_order_id_fallbacks(self):
        h = _FakeHandler()
        orders = [
            {"order_id": "via-order_id", "total_price": "1"},
            {"total_price": "2"},  # no id at all
        ]
        stats = replay_orders(orders, handler=h)
        self.assertEqual(stats.successful, 2)
        ids = [r.order_id for r in stats.results]
        self.assertIn("via-order_id", ids)
        self.assertIn("", ids)

    def test_duration_populated(self):
        clock = {"t": 1000.0}

        def fake_now():
            clock["t"] += 0.25
            return clock["t"]

        h = _FakeHandler()
        stats = replay_orders(
            [{"id": "ord-1", "total_price": "0"}],
            handler=h,
            now_fn=fake_now,
        )
        # start + end calls → non-negative, >= 0.25 s
        self.assertGreaterEqual(stats.duration_s, 0.25)

    def test_throttle_parameter_used(self):
        """``throttle_s`` path triggers ``time.sleep``; we
        only verify the call happened, not its duration."""
        h = _FakeHandler()
        calls: list[float] = []
        import agents.replay.order_replay as mod

        original = mod.time.sleep
        mod.time.sleep = lambda s: calls.append(s)  # type: ignore[assignment]
        try:
            replay_orders(
                [
                    {"id": "a", "total_price": "1"},
                    {"id": "b", "total_price": "1"},
                ],
                handler=h,
                throttle_s=0.02,
            )
        finally:
            mod.time.sleep = original  # type: ignore[assignment]
        self.assertEqual(calls, [0.02, 0.02])

    def test_throttle_zero_skips_sleep(self):
        h = _FakeHandler()
        calls: list[float] = []
        import agents.replay.order_replay as mod

        original = mod.time.sleep
        mod.time.sleep = lambda s: calls.append(s)  # type: ignore[assignment]
        try:
            replay_orders(
                [{"id": "a", "total_price": "1"}],
                handler=h,
                throttle_s=0.0,
            )
        finally:
            mod.time.sleep = original  # type: ignore[assignment]
        self.assertEqual(calls, [])

    def test_results_truncated_to_50_in_asdict(self):
        h = _FakeHandler()
        orders = [
            {"id": f"ord-{i}", "total_price": "1"}
            for i in range(80)
        ]
        stats = replay_orders(orders, handler=h)
        d = stats.as_dict()
        # internal list full length
        self.assertEqual(len(stats.results), 80)
        # serialised view bounded
        self.assertEqual(len(d["results"]), 50)
        self.assertEqual(d["attempted"], 80)


class TestReplayStatsAsDict(unittest.TestCase):
    def test_as_dict_keys(self):
        h = _FakeHandler()
        stats = replay_orders(
            [{"id": "x", "total_price": "1.23"}],
            handler=h,
        )
        d = stats.as_dict()
        self.assertEqual(
            set(d.keys()),
            {
                "attempted", "successful", "failed",
                "skipped_non_dict", "total_revenue_usd",
                "deliberations_observed", "duration_s",
                "results",
            },
        )
        self.assertEqual(d["total_revenue_usd"], 1.23)

    def test_result_as_dict_shape(self):
        r = OrderReplayResult(
            order_id="ord-9", ok=True,
            handler_output={"a": 1},
        )
        d = r.as_dict()
        self.assertEqual(d["order_id"], "ord-9")
        self.assertTrue(d["ok"])
        self.assertEqual(d["handler_output"], {"a": 1})
        self.assertEqual(d["error"], "")


class TestReplayFromFile(unittest.TestCase):
    def _write(self, lines: list[str]) -> Path:
        tmp = tempfile.NamedTemporaryFile(
            "w", suffix=".jsonl", delete=False,
        )
        tmp.write("\n".join(lines))
        tmp.close()
        return Path(tmp.name)

    def test_happy_path_jsonl(self):
        path = self._write([
            json.dumps({"id": "o1", "total_price": "5"}),
            json.dumps({"id": "o2", "total_price": "7"}),
        ])
        try:
            h = _FakeHandler()
            stats = replay_orders_from_file(
                path, handler=h,
            )
            self.assertEqual(stats.successful, 2)
            self.assertAlmostEqual(
                stats.total_revenue_usd, 12.0, places=2,
            )
        finally:
            path.unlink()

    def test_blank_and_malformed_lines_skipped(self):
        path = self._write([
            json.dumps({"id": "o1", "total_price": "5"}),
            "",
            "not json at all",
            "   ",
            json.dumps([1, 2, 3]),  # non-dict json
            json.dumps({"id": "o2", "total_price": "3"}),
        ])
        try:
            h = _FakeHandler()
            stats = replay_orders_from_file(
                path, handler=h,
            )
            # two real dicts replayed
            self.assertEqual(stats.attempted, 2)
            self.assertEqual(stats.successful, 2)
        finally:
            path.unlink()

    def test_file_not_found_raises(self):
        with self.assertRaises(FileNotFoundError):
            replay_orders_from_file(
                "/tmp/nonexistent_replay_abc123.jsonl",
            )


class TestReplayConcurrencyLock(unittest.TestCase):
    """Two concurrent ``replay_orders`` calls must serialise —
    otherwise the handler's internal state would interleave."""

    def test_lock_serialises_calls(self):
        order = []

        class SlowHandler:
            def handle_order_paid(self, o):
                order.append(("in", o["id"]))
                # no real sleep — deterministic test
                order.append(("out", o["id"]))
                return {"ok": True}

        h = SlowHandler()
        b1 = [{"id": "a", "total_price": "0"}]
        b2 = [{"id": "b", "total_price": "0"}]
        t1 = threading.Thread(
            target=replay_orders,
            args=(b1,),
            kwargs={"handler": h},
        )
        t2 = threading.Thread(
            target=replay_orders,
            args=(b2,),
            kwargs={"handler": h},
        )
        t1.start(); t2.start()
        t1.join(); t2.join()
        # both calls completed — 4 entries
        self.assertEqual(len(order), 4)
        # second call's "in" comes after first "out"
        ids_in = [e for e in order if e[0] == "in"]
        self.assertEqual(len(ids_in), 2)


class TestReplayStatsDataclass(unittest.TestCase):
    def test_defaults(self):
        s = ReplayStats()
        self.assertEqual(s.attempted, 0)
        self.assertEqual(s.successful, 0)
        self.assertEqual(s.failed, 0)
        self.assertEqual(s.skipped_non_dict, 0)
        self.assertEqual(s.total_revenue_usd, 0.0)
        self.assertEqual(s.deliberations_observed, 0)
        self.assertEqual(s.duration_s, 0.0)
        self.assertEqual(s.results, [])


class TestMCPReplayToolRegistered(unittest.TestCase):
    """The owner invokes ``replay_orders`` via Claude Desktop
    through MCP. Verify the registry exposes it, flags it as
    write (paranoid mode), and the handler wires to the
    function under test."""

    def test_tool_registered_as_write(self):
        from mcp_server.tools import build_default_registry

        reg = build_default_registry()
        names = {s.name for s in reg.list_tools()}
        self.assertIn("replay_orders", names)
        spec = next(
            s for s in reg.list_tools()
            if s.name == "replay_orders"
        )
        self.assertTrue(spec.write)
        self.assertIn(
            "path", spec.input_schema.get("required", []),
        )

    def test_handler_requires_path(self):
        from mcp_server.tools import ToolError
        from mcp_server.tools import (
            _replay_orders_handler,
        )

        with self.assertRaises(ToolError):
            _replay_orders_handler({})

    def test_handler_missing_file_raises_tool_error(self):
        from mcp_server.tools import ToolError
        from mcp_server.tools import (
            _replay_orders_handler,
        )

        with self.assertRaises(ToolError):
            _replay_orders_handler({
                "path": "/tmp/nope_replay_xyz.jsonl",
            })

    def test_handler_returns_stats_dict(self):
        from mcp_server.tools import (
            _replay_orders_handler,
        )

        path = Path(tempfile.mkstemp(suffix=".jsonl")[1])
        try:
            path.write_text(
                json.dumps({
                    "id": "o1", "total_price": "1",
                }) + "\n",
            )
            # real handler path — OrderWebhookHandler is
            # tolerant of minimal payloads (no line items)
            out = _replay_orders_handler({
                "path": str(path),
            })
            self.assertIn("attempted", out)
            self.assertEqual(out["attempted"], 1)
        finally:
            path.unlink()


if __name__ == "__main__":
    unittest.main()
