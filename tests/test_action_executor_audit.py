"""Tests for audit-pass-17 fixes in execution/action_executor.

  1. action_id was `f"act_{int(time.time()*1000)}"` — millisecond
     timestamps collide when multiple actions are proposed in the
     same millisecond. The id-based dedup filters then removed
     BOTH actions sharing an id, and _find_pending returned the
     wrong one.
  2. propose_action stored the caller's params dict by REFERENCE.
     Any mutation by the caller (or by _dispatch_action's
     `params.pop("product_id")`) leaked into the audit log entry
     and any retry logic that re-read the action.
  3. _pending_actions / _action_log mutations had no thread lock.
     Concurrent propose_action / approve_all calls could race.
  4. get_stats and _find_pending used direct `a["status"]` /
     `a["id"]` access — a malformed log entry crashed with
     KeyError.
"""
import threading

import pytest


def _executor():
    """Build an ActionExecutor with a stub store_manager that
    short-circuits dispatch (we test the pipeline, not Shopify)."""
    from execution.action_executor import ActionExecutor

    class _StubSM:
        def get_credentials(self, store_id):
            return {"shop_url": "x", "api_key": "y"}

    ex = ActionExecutor(_StubSM())
    # Stub _dispatch_action so tests don't need real Shopify
    ex._dispatch_action = lambda atype, creds, params: {"ok": True, "atype": atype}
    return ex


# ── Action ID uniqueness ────────────────────────────────────


class TestActionIdUniqueness:
    def test_two_proposes_in_same_millisecond_unique_ids(self):
        """Regression: previously both proposes inside the same
        millisecond got the same `act_<ms>` id and the dedup
        filter removed both at once."""
        ex = _executor()
        a1 = ex.propose_action({"type": "x", "store_id": "s"})
        a2 = ex.propose_action({"type": "x", "store_id": "s"})
        a3 = ex.propose_action({"type": "x", "store_id": "s"})
        assert a1["id"] != a2["id"]
        assert a2["id"] != a3["id"]
        assert a1["id"] != a3["id"]
        # All three queued
        assert len(ex.get_pending()) == 3

    def test_id_format_stable(self):
        ex = _executor()
        a = ex.propose_action({"type": "x"})
        assert a["id"].startswith("act_")
        assert len(a["id"]) > len("act_")


# ── Params mutation isolation ───────────────────────────────


class TestParamsMutationIsolation:
    def test_caller_mutation_does_not_leak_into_proposed(self):
        ex = _executor()
        caller_params = {"product_id": "p1", "price": 10}
        proposed = ex.propose_action({
            "type": "update_price",
            "store_id": "s",
            "params": caller_params,
        })
        # Caller mutates after proposing
        caller_params["price"] = 99
        caller_params["new_field"] = "leak"
        # Proposed action keeps the original snapshot
        assert proposed["params"]["price"] == 10
        assert "new_field" not in proposed["params"]

    def test_dispatcher_mutation_does_not_leak_into_log(self):
        """Regression: previously _dispatch_action's destructive
        `params.pop("product_id")` mutated the action's stored
        params, so the audit log lost the original product_id."""
        ex = _executor()
        # Replace dispatcher with one that destructively pops
        def _destructive(atype, creds, params):
            params.pop("product_id", None)
            params.pop("variant_id", None)
            return {"ok": True}
        ex._dispatch_action = _destructive

        action = ex.propose_action({
            "type": "update_price",
            "store_id": "s",
            "params": {"product_id": "p1", "variant_id": "v1", "price": 10},
        })
        ex._auto_approve = True  # ensure execute path
        ex.approve_action(action["id"])

        # Find the executed action in the log
        log = ex.get_action_log()
        executed = [a for a in log if a.get("status") == "executed"]
        assert executed
        # Original params still intact in the audit trail
        assert executed[0]["params"]["product_id"] == "p1"
        assert executed[0]["params"]["variant_id"] == "v1"


# ── Thread safety ───────────────────────────────────────────


class TestThreadSafety:
    def test_concurrent_proposes_all_recorded(self):
        """All proposes from concurrent threads should land in
        the pending queue exactly once each."""
        ex = _executor()
        errors: list[Exception] = []

        def worker(n):
            try:
                for _ in range(20):
                    ex.propose_action({"type": "x", "store_id": f"s{n}"})
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        # 5 threads * 20 proposes = 100 unique pending actions
        pending = ex.get_pending()
        assert len(pending) == 100
        # All ids unique
        ids = {a["id"] for a in pending}
        assert len(ids) == 100

    def test_concurrent_approve_and_propose(self):
        ex = _executor()

        def proposer():
            for _ in range(30):
                ex.propose_action({"type": "x", "store_id": "s"})

        def approver():
            for _ in range(30):
                pending = ex.get_pending()
                if pending:
                    ex.approve_action(pending[0]["id"])

        t1 = threading.Thread(target=proposer)
        t2 = threading.Thread(target=approver)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # No crashes; final state is consistent (pending + log == 30)
        stats = ex.get_stats()
        assert stats["pending"] + stats["executed"] == 30


# ── Defensive .get on log entries ───────────────────────────


class TestDefensiveStatusAccess:
    def test_get_stats_handles_missing_status(self):
        ex = _executor()
        # Inject a malformed log entry without "status"
        with ex._lock:
            ex._action_log.append({"id": "broken", "type": "x"})
        # Must not crash
        stats = ex.get_stats()
        assert stats["total"] == 1
        assert stats["executed"] == 0

    def test_find_pending_handles_missing_id(self):
        ex = _executor()
        with ex._lock:
            ex._pending_actions.append({"type": "broken_no_id"})
        # Must not crash even though the entry has no id
        result = ex._find_pending("nope")
        assert result is None
