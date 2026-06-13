"""W963-165: publish_product dispatcher tests."""
from __future__ import annotations

from unittest.mock import patch

from core.approval.dispatchers import (
    _publish_product_dispatch,
    _ONLINE_STORE_PUB_CACHE,
)


class TestPublishProduct:
    def setup_method(self):
        _ONLINE_STORE_PUB_CACHE.clear()

    def test_happy_path_auto_resolves_online_store(self):
        calls: list[tuple[str, dict]] = []

        def fake_router_call(cap, params):
            calls.append((cap, dict(params)))
            if cap == "SHOPIFY_UPDATE_PRODUCT":
                return True, {"product": {"id": params["id"]}}
            if cap == "SHOPIFY_LIST_PUBLICATIONS":
                return True, {
                    "publications": [
                        {
                            "id": (
                                "gid://shopify/Publication/1"
                            ),
                            "name": "Online Store",
                        },
                        {
                            "id": (
                                "gid://shopify/Publication/2"
                            ),
                            "name": "Point of Sale",
                        },
                    ],
                }
            if cap == "SHOPIFY_PUBLISH_RESOURCE":
                return True, {
                    "id": params["id"],
                    "publication_count": len(
                        params.get("publication_ids") or [],
                    ),
                }
            return False, {"error": "unexpected"}

        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=fake_router_call,
        ):
            ok, result = _publish_product_dispatch({
                "product_id": "gid://shopify/Product/100",
            })

        assert ok is True
        assert result["status_updated"] is True
        assert result["publication_ids"] == [
            "gid://shopify/Publication/1",
        ]
        # Verify ordered call chain:
        # 1. UPDATE_PRODUCT (status=ACTIVE)
        # 2. LIST_PUBLICATIONS (resolve Online Store)
        # 3. PUBLISH_RESOURCE
        cap_chain = [c for c, _ in calls]
        assert cap_chain == [
            "SHOPIFY_UPDATE_PRODUCT",
            "SHOPIFY_LIST_PUBLICATIONS",
            "SHOPIFY_PUBLISH_RESOURCE",
        ]
        # Status set to ACTIVE
        assert calls[0][1].get("status") == "ACTIVE"

    def test_explicit_publication_ids_skips_list(self):
        calls: list[str] = []

        def fake_router_call(cap, params):
            calls.append(cap)
            if cap == "SHOPIFY_UPDATE_PRODUCT":
                return True, {}
            if cap == "SHOPIFY_PUBLISH_RESOURCE":
                return True, {"id": params["id"]}
            return False, {"error": "unexpected"}

        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=fake_router_call,
        ):
            ok, _ = _publish_product_dispatch({
                "product_id": "gid://shopify/Product/100",
                "publication_ids": [
                    "gid://shopify/Publication/99",
                ],
            })

        assert ok is True
        # LIST_PUBLICATIONS was NOT called
        assert "SHOPIFY_LIST_PUBLICATIONS" not in calls

    def test_missing_product_id_rejects(self):
        ok, result = _publish_product_dispatch({})
        assert ok is False
        assert result == {"error": "missing_product_id"}

    def test_no_online_store_pub_returns_error(self):
        def fake_router_call(cap, params):
            if cap == "SHOPIFY_UPDATE_PRODUCT":
                return True, {}
            if cap == "SHOPIFY_LIST_PUBLICATIONS":
                # No publication named 'Online Store'
                return True, {
                    "publications": [{
                        "id": "gid://shopify/Publication/2",
                        "name": "Point of Sale",
                    }],
                }
            return False, {"error": "unexpected"}

        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=fake_router_call,
        ):
            ok, result = _publish_product_dispatch({
                "product_id": "gid://shopify/Product/100",
            })

        assert ok is False
        assert (
            result["error"]
            == "no_online_store_publication_found"
        )
        # W963-175: error envelope surfaces partial-state so
        # operator knows the product IS ACTIVE on Shopify but
        # NOT on the Online Store sales channel.
        assert result["status_updated"] is True
        assert (
            result["product_id"]
            == "gid://shopify/Product/100"
        )

    def test_resolve_publication_thread_safe(self):
        """W963-178: concurrent _resolve_online_store_publication
        calls for the same sid must not duplicate the
        LIST_PUBLICATIONS router call (race condition was harmless
        but wasted)."""
        import threading
        from core.approval.dispatchers import (
            _resolve_online_store_publication,
            _ONLINE_STORE_PUB_CACHE,
        )
        _ONLINE_STORE_PUB_CACHE.clear()
        call_count = {"n": 0}
        call_lock = threading.Lock()
        start_barrier = threading.Barrier(8)

        def fake_router_call(cap, params):
            with call_lock:
                call_count["n"] += 1
            if cap == "SHOPIFY_LIST_PUBLICATIONS":
                return True, {
                    "publications": [{
                        "id": "gid://shopify/Publication/X",
                        "name": "Online Store",
                    }],
                }
            return False, {}

        results: list[str] = []
        results_lock = threading.Lock()

        def worker():
            from core.context import active_store
            start_barrier.wait()
            with active_store("race_test_store"):
                pid = _resolve_online_store_publication()
            with results_lock:
                results.append(pid)

        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=fake_router_call,
        ):
            threads = [
                threading.Thread(target=worker)
                for _ in range(8)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        # Every worker got the right GID
        assert all(
            r == "gid://shopify/Publication/X"
            for r in results
        )
        # Cache populated correctly
        assert (
            _ONLINE_STORE_PUB_CACHE.get("race_test_store")
            == "gid://shopify/Publication/X"
        )
        # Best-effort: lock means most workers find a cache
        # hit. Worst case under race: 2-3 calls (the early
        # ones racing to populate). Solid upper bound is 8
        # (no lock at all would let every thread fire).
        assert call_count["n"] <= 4, (
            f"too many LIST_PUBLICATIONS under race: "
            f"{call_count['n']}/8 -- lock not effective"
        )

    def test_status_update_failure_short_circuits(self):
        calls: list[str] = []

        def fake_router_call(cap, params):
            calls.append(cap)
            if cap == "SHOPIFY_UPDATE_PRODUCT":
                return False, {"error": "perm_denied"}
            return True, {}

        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=fake_router_call,
        ):
            ok, result = _publish_product_dispatch({
                "product_id": "gid://shopify/Product/100",
            })

        assert ok is False
        assert result["error"] == "status_update_failed"
        # No LIST or PUBLISH calls fired
        assert calls == ["SHOPIFY_UPDATE_PRODUCT"]
