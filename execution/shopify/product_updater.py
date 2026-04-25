"""ProductUpdater — updates existing Shopify products via the REST Admin API.

Uses only the Python standard library (urllib.request / urllib.error).
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any


class ProductUpdater:
    """Updates products, inventory, and prices on a Shopify store."""

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def update_product(
        self,
        shop_url: str,
        api_key: str,
        product_id: str | int,
        updates: dict[str, Any],
        *,
        verify: bool = True,
    ) -> dict[str, Any]:
        """PUT updated fields onto an existing Shopify product.

        Args:
            shop_url:   e.g. ``"mystore.myshopify.com"``
            api_key:    Shopify Admin API access token.
            product_id: Numeric Shopify product ID.
            updates:    Dict of fields to change (title, body_html, tags, …).
            verify:     When True (default), the write is followed by a
                        read-back through ``post_write_verifier``;
                        any field drift is attached as
                        ``{"drift": {...}}`` in the response. The
                        write itself still reports ``status="updated"``
                        — callers decide whether drift is fatal.

        Returns:
            ``{"status": "updated", "product": {...}, "drift": {...}}`` or
            ``{"status": "error", "error": "..."}``
        """
        url = self._build_url(shop_url, f"/admin/api/2024-01/products/{product_id}.json")
        headers = self._build_headers(api_key)
        payload = {"product": {"id": product_id, **updates}}

        try:
            response = self._make_request("PUT", url, headers, payload)
            result = {
                "status": "updated",
                "product": response.get("product", response),
            }
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

        if verify and updates:
            drift = self._verify_product(
                shop_url=shop_url,
                api_key=api_key,
                product_id=product_id,
                expected=updates,
            )
            if drift is not None:
                result["drift"] = drift
        return result

    def update_inventory(
        self,
        shop_url: str,
        api_key: str,
        inventory_item_id: str | int,
        location_id: str | int,
        quantity: int,
    ) -> dict[str, Any]:
        """Set the inventory level for an item at a specific location.

        Calls the ``/admin/api/2024-01/inventory_levels/set.json`` endpoint.

        Returns:
            ``{"status": "updated", "inventory_level": {...}}`` or error dict.
        """
        url = self._build_url(
            shop_url, "/admin/api/2024-01/inventory_levels/set.json"
        )
        headers = self._build_headers(api_key)
        payload = {
            "location_id": location_id,
            "inventory_item_id": inventory_item_id,
            "available": quantity,
        }

        try:
            response = self._make_request("POST", url, headers, payload)
            return {
                "status": "updated",
                "inventory_level": response.get("inventory_level", response),
            }
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    def update_price(
        self,
        shop_url: str,
        api_key: str,
        product_id: str | int,
        variant_id: str | int,
        new_price: float | str,
        *,
        verify: bool = True,
    ) -> dict[str, Any]:
        """Update the price of a specific product variant.

        Args:
            variant_id: Shopify variant ID to change.
            new_price:  New price (will be cast to a 2-decimal string).
            verify:     Read-back after the write and attach drift info
                        when the actual price differs from expected.

        Returns:
            ``{"status": "updated", "variant": {...}, "drift": {...}}``
            or error dict.
        """
        price_str = f"{float(new_price):.2f}"
        url = self._build_url(
            shop_url, f"/admin/api/2024-01/variants/{variant_id}.json"
        )
        headers = self._build_headers(api_key)
        payload = {"variant": {"id": variant_id, "price": price_str}}

        try:
            response = self._make_request("PUT", url, headers, payload)
            result = {
                "status": "updated",
                "variant": response.get("variant", response),
            }
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

        if verify:
            drift = self._verify_variant(
                shop_url=shop_url,
                api_key=api_key,
                variant_id=variant_id,
                expected={"price": price_str},
            )
            if drift is not None:
                result["drift"] = drift
        return result

    def update_bulk(
        self,
        shop_url: str,
        api_key: str,
        updates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Apply multiple product updates sequentially.

        Each entry in *updates* must contain at least ``product_id`` and the
        fields to change.  Optional keys ``variant_id`` + ``price`` trigger
        :meth:`update_price`; ``inventory_item_id`` + ``location_id`` +
        ``quantity`` trigger :meth:`update_inventory`; everything else
        calls :meth:`update_product`.

        Returns:
            ``{"results": [...], "errors": [...], "total": N,
               "succeeded": N, "failed": N}``
        """
        results: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []

        for idx, entry in enumerate(updates):
            product_id = entry.get("product_id")
            if not product_id:
                errors.append({"index": idx, "error": "Missing 'product_id'"})
                continue

            # Inventory update branch
            if "inventory_item_id" in entry and "location_id" in entry and "quantity" in entry:
                result = self.update_inventory(
                    shop_url,
                    api_key,
                    entry["inventory_item_id"],
                    entry["location_id"],
                    entry["quantity"],
                )
            # Price update branch
            elif "variant_id" in entry and "price" in entry:
                result = self.update_price(
                    shop_url, api_key, product_id, entry["variant_id"], entry["price"]
                )
            else:
                # Generic product field update
                fields = {
                    k: v
                    for k, v in entry.items()
                    if k not in ("product_id",)
                }
                result = self.update_product(shop_url, api_key, product_id, fields)

            if result.get("status") in ("updated",):
                results.append({**result, "index": idx})
            else:
                errors.append({"index": idx, "entry": entry, "error": result})

        return {
            "results": results,
            "errors": errors,
            "total": len(updates),
            "succeeded": len(results),
            "failed": len(errors),
        }

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    def _make_request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """HTTP request via urllib with 429 retry and exponential back-off."""
        data: bytes | None = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers = {**headers, "Content-Type": "application/json"}

        max_retries = 3
        delay = 1.0

        for attempt in range(max_retries + 1):
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    body = resp.read().decode("utf-8")
                    return json.loads(body) if body else {}
            except urllib.error.HTTPError as exc:
                if exc.code == 429 and attempt < max_retries:
                    retry_after = float(exc.headers.get("Retry-After", delay))
                    time.sleep(retry_after)
                    delay *= 2
                    continue
                body = exc.read().decode("utf-8", errors="replace")
                raise urllib.error.HTTPError(
                    url, exc.code, f"{exc.reason} — {body}", exc.headers, None
                ) from exc
            except urllib.error.URLError:
                if attempt < max_retries:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise

        raise RuntimeError(f"Request to {url} failed after {max_retries} retries.")

    @staticmethod
    def _build_url(shop_url: str, path: str) -> str:
        host = shop_url.rstrip("/")
        if not host.startswith("http"):
            host = f"https://{host}"
        return f"{host}{path}"

    @staticmethod
    def _build_headers(api_key: str) -> dict[str, str]:
        return {
            "X-Shopify-Access-Token": api_key,
            "Accept": "application/json",
        }

    # ------------------------------------------------------------------ #
    # Post-write verification (D2 wire-in)                                 #
    # ------------------------------------------------------------------ #

    def _fetch_product(
        self, shop_url: str, api_key: str,
        product_id: str | int,
    ) -> dict[str, Any]:
        url = self._build_url(
            shop_url,
            f"/admin/api/2024-01/products/{product_id}.json",
        )
        headers = self._build_headers(api_key)
        body = self._make_request("GET", url, headers)
        return body.get("product") or body or {}

    def _fetch_variant(
        self, shop_url: str, api_key: str,
        variant_id: str | int,
    ) -> dict[str, Any]:
        url = self._build_url(
            shop_url,
            f"/admin/api/2024-01/variants/{variant_id}.json",
        )
        headers = self._build_headers(api_key)
        body = self._make_request("GET", url, headers)
        return body.get("variant") or body or {}

    def _verify_product(
        self, *,
        shop_url: str,
        api_key: str,
        product_id: str | int,
        expected: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Read the product back and return a drift dict if any
        expected field differs. Returns ``None`` when everything
        matches (success — no drift).
        """
        try:
            from execution.verify.post_write_verifier import (
                verify_write,
            )
        except Exception:  # noqa: BLE001
            return None
        # Only verify fields we actually wrote.
        fields = tuple(expected.keys())
        if not fields:
            return None
        report = verify_write(
            read_fn=lambda: self._fetch_product(
                shop_url, api_key, product_id,
            ),
            expected=expected,
            fields=fields,
            tolerance={
                "price": 0.01,
                "compare_at_price": 0.01,
            },
            allow_missing=(
                "body_html", "tags", "metafields",
            ),
        )
        if not report.drift:
            return None
        self._emit_drift_outcome(
            resource="product",
            resource_id=str(product_id),
            diffs=list(report.field_diffs),
            read_ok=report.read_ok,
            error=report.error,
        )
        return report.as_dict()

    def _verify_variant(
        self, *,
        shop_url: str,
        api_key: str,
        variant_id: str | int,
        expected: dict[str, Any],
    ) -> dict[str, Any] | None:
        try:
            from execution.verify.post_write_verifier import (
                verify_write,
            )
        except Exception:  # noqa: BLE001
            return None
        report = verify_write(
            read_fn=lambda: self._fetch_variant(
                shop_url, api_key, variant_id,
            ),
            expected=expected,
            fields=tuple(expected.keys()),
            tolerance={"price": 0.01},
        )
        if not report.drift:
            return None
        self._emit_drift_outcome(
            resource="variant",
            resource_id=str(variant_id),
            diffs=list(report.field_diffs),
            read_ok=report.read_ok,
            error=report.error,
        )
        return report.as_dict()

    def _emit_drift_outcome(
        self,
        *,
        resource: str,
        resource_id: str,
        diffs: list[dict[str, Any]],
        read_ok: bool,
        error: str,
    ) -> None:
        """Best-effort fire a learning signal when a Shopify
        write drifts from expectation. Silent on missing deps."""
        try:
            from core.integration.engine_outcome_bus import (
                EngineOutcome,
                get_engine_outcome_bus,
            )
            get_engine_outcome_bus().report(EngineOutcome(
                engine="shopify_product_updater",
                kpi="execution_drift",
                value=float(len(diffs)),
                ok=False,
                source="shopify",
                context={
                    "resource": resource,
                    "resource_id": resource_id,
                    "diffs": diffs,
                    "read_ok": read_ok,
                    "error": error,
                },
            ))
        except Exception:  # noqa: BLE001
            # Drift emission is diagnostic, never fatal.
            pass
