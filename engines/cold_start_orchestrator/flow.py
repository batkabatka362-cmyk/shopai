"""Cold Start Orchestrator — Pattern Q envelope.

Composes multiple W963 engines into a single end-to-end run.
Each sub-step is wrapped in try/except so an engine failure
doesn't break the whole chain — the failure surfaces in that
step's slice of the output report.
"""
from __future__ import annotations

import copy
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class ColdStartOrchestratorEngine:
    ENGINE_NAME = "cold_start_orchestrator"

    def run(
        self, input_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        start = time.monotonic()
        payload = self._safe_copy(input_payload)
        if payload is None:
            return self._fail("Input copy failed", 0.0)
        if not isinstance(payload, dict):
            return self._fail("Input must be a dict", 0.0)
        if payload.get("status") == "fail":
            return self._fail(
                payload.get("error", "Upstream failure"), 0.0,
            )

        data = payload.get("data") or {}
        if not isinstance(data, dict):
            data = {}

        store_id = data.get("store_id")
        niche = (data.get("niche") or "general").lower()
        blog_id = data.get("blog_id")
        apply_flag = bool(data.get("apply", False))

        # Container for per-step results.
        report: dict[str, Any] = {
            "store_id": store_id,
            "niche": niche,
            "apply_mode": apply_flag,
            "steps": {},
            "next_actions": [],
        }

        # ── Step 1: Revenue readiness ────────────────────
        diag = self._step_diagnose(store_id)
        report["steps"]["diagnose"] = diag
        verdict = diag.get("verdict", "unknown")
        gates = diag.get("gates_passed", 0)
        total = diag.get("gates_total", 6)

        if verdict == "earning_active":
            report["next_actions"].append(
                "Already earning -- monitor via shopai earnings + "
                "shopai daily-brief"
            )
            elapsed = time.monotonic() - start
            return self._success(report, elapsed)

        # ── Step 2: Product seeding ───────────────────────
        if diag.get("has_products_status") in (
            "missing", "partial",
        ):
            report["steps"]["product_seed"] = self._step_seed_products(
                niche=niche, apply_flag=apply_flag,
            )
            if not apply_flag:
                report["next_actions"].append(
                    "shopai earn-bootstrap --niche "
                    f"{niche} --yes  (seed 20 DRAFT products)"
                )

        # ── Step 3: Blog content seeding ──────────────────
        report["steps"]["blog_seed"] = self._step_seed_blog(
            niche=niche, blog_id=blog_id, apply_flag=apply_flag,
        )
        if not apply_flag or not blog_id:
            report["next_actions"].append(
                "shopai blog-candidates --niche "
                f"{niche} --apply --blog-id <BLOG_GID>  "
                "(needs Shopify Blog GID -- Admin -> Online "
                "Store -> Blog Posts)"
            )

        # ── Step 4: CRO variants for first product ────────
        report["steps"]["cro"] = self._step_cro_preview(niche=niche)

        # ── Step 5: Channel readiness ─────────────────────
        report["steps"]["channels"] = self._step_channel_status()
        ch = report["steps"]["channels"]
        if not ch.get("ads_ready"):
            report["next_actions"].append(
                "shopai ads connect meta --token X "
                "--account-id Y  (paid traffic substrate)"
            )
        if not ch.get("email_ready"):
            report["next_actions"].append(
                "shopai email connect brevo --api-key X  "
                "(transactional + marketing email)"
            )
        if not ch.get("pinterest_ready"):
            report["next_actions"].append(
                "shopai pinterest connect --token X  "
                "(visual organic traffic)"
            )
        if not ch.get("instagram_ready"):
            report["next_actions"].append(
                "Set INSTAGRAM_ACCESS_TOKEN + "
                "INSTAGRAM_ACCOUNT_ID  "
                "(visual + paid social via Meta Graph API)"
            )
        if not ch.get("tiktok_ready"):
            report["next_actions"].append(
                "shopai tiktok connect --token X "
                "--business-id Y  (short-form video)"
            )

        # ── Step 6: Earnings snapshot ─────────────────────
        report["steps"]["earnings"] = self._step_earnings(
            store_id,
        )

        # Overall verdict + headline.
        report["headline"] = (
            f"Cold-start orchestrator run: {verdict} "
            f"({gates}/{total} gates). "
            f"{len(report['next_actions'])} next action(s)."
        )

        elapsed = time.monotonic() - start
        return self._success(report, elapsed)

    # ── Step helpers ──────────────────────────────────────

    @staticmethod
    def _step_diagnose(store_id: Any) -> dict[str, Any]:
        try:
            from engines.revenue_readiness import (
                RevenueReadinessEngine,
            )
            payload: dict[str, Any] = {"data": {}}
            if store_id:
                payload["data"]["store_id"] = store_id
            result = RevenueReadinessEngine().run(payload)
            d = result.get("data") or {}
            gates = d.get("gates") or []
            has_products = next(
                (
                    g for g in gates
                    if g.get("name") == "has_products"
                ),
                {},
            )
            return {
                "ok": result.get("status") == "success",
                "verdict": d.get("verdict", "unknown"),
                "gates_passed": d.get("passed", 0),
                "gates_total": d.get("total", 6),
                "has_products_status": has_products.get(
                    "status", "unknown",
                ),
                "next_action": d.get("next_action", ""),
            }
        except Exception as exc:  # noqa: BLE001
            logger.debug("diagnose step raised: %s", exc)
            return {
                "ok": False,
                "error": str(exc)[:120],
            }

    @staticmethod
    def _step_seed_products(
        *, niche: str, apply_flag: bool,
    ) -> dict[str, Any]:
        try:
            from engines.product_sourcer import (
                ProductSourcerEngine,
            )
            payload = {
                "data": {
                    "niche": niche,
                    "count": 20,
                    "apply_candidates": apply_flag,
                },
            }
            if apply_flag:
                payload["data"]["require_approval"] = True
            result = ProductSourcerEngine().run(payload)
            d = result.get("data") or {}
            return {
                "ok": result.get("status") == "success",
                "candidates_generated": d.get(
                    "count_returned", 0,
                ),
                "pending_actions": len(
                    d.get("pending_actions") or [],
                ),
                "next_action": d.get("next_action", ""),
            }
        except Exception as exc:  # noqa: BLE001
            logger.debug("product_seed step raised: %s", exc)
            return {"ok": False, "error": str(exc)[:120]}

    @staticmethod
    def _step_seed_blog(
        *,
        niche: str,
        blog_id: str | None,
        apply_flag: bool,
    ) -> dict[str, Any]:
        try:
            from engines.content_publisher import (
                ContentPublisherEngine,
            )
            payload = {
                "data": {
                    "niche": niche,
                    "count": 10,
                    "apply_candidates": apply_flag,
                },
            }
            if blog_id:
                payload["data"]["blog_id"] = blog_id
            result = ContentPublisherEngine().run(payload)
            d = result.get("data") or {}
            return {
                "ok": result.get("status") == "success",
                "candidates_generated": d.get(
                    "count_returned", 0,
                ),
                "pending_actions": len(
                    d.get("pending_actions") or [],
                ),
                "next_action": d.get("next_action", ""),
            }
        except Exception as exc:  # noqa: BLE001
            logger.debug("blog_seed step raised: %s", exc)
            return {"ok": False, "error": str(exc)[:120]}

    @staticmethod
    def _step_cro_preview(*, niche: str) -> dict[str, Any]:
        """Preview CRO variants for a synthetic product in the
        niche. Operator can use these as a template for real
        product variants."""
        try:
            from engines.cro_variants import CroVariantsEngine
            # Use a synthetic product based on niche so the
            # operator sees what variants look like.
            from engines.product_sourcer.catalogs import (
                get_catalog,
            )
            catalog = get_catalog(niche)
            if not catalog:
                return {
                    "ok": False,
                    "error": f"no catalog for niche '{niche}'",
                }
            first = catalog[0]
            result = CroVariantsEngine().run({
                "data": {
                    "product": {
                        "title": first.name,
                        "description": first.description,
                        "category": first.category,
                        "price": (
                            first.price_min + first.price_max
                        ) / 2,
                    },
                    "strategies": ["title", "description", "price"],
                },
            })
            d = result.get("data") or {}
            variants = d.get("variants") or {}
            return {
                "ok": result.get("status") == "success",
                "sample_product": first.name,
                "title_variant_count": len(
                    variants.get("title") or [],
                ),
                "description_variant_count": len(
                    variants.get("description") or [],
                ),
                "price_variant_count": len(
                    variants.get("price") or [],
                ),
            }
        except Exception as exc:  # noqa: BLE001
            logger.debug("cro_preview step raised: %s", exc)
            return {"ok": False, "error": str(exc)[:120]}

    @staticmethod
    def _step_channel_status() -> dict[str, Any]:
        """Per-channel readiness without live probes. Read-only."""
        out: dict[str, Any] = {
            "ads_ready": False,
            "email_ready": False,
            "pinterest_ready": False,
            "tiktok_ready": False,
            "instagram_ready": False,
        }
        # Ads
        try:
            from engines.ads_launcher.status import (
                get_all_status as ads_status,
            )
            ads = ads_status()
            out["ads_ready"] = any(
                s.ready for s in ads.values()
            )
        except Exception:  # noqa: BLE001
            pass
        # Email
        try:
            from engines.email_connect.status import (
                get_all_status as email_status,
            )
            emails = email_status()
            out["email_ready"] = any(
                s.ready for s in emails.values()
            )
        except Exception:  # noqa: BLE001
            pass
        # Pinterest
        try:
            from engines.pinterest_publisher.status import (
                get_status as pinterest_status,
            )
            out["pinterest_ready"] = pinterest_status(
                skip_live=True,
            ).ready
        except Exception:  # noqa: BLE001
            pass
        # TikTok
        try:
            from engines.tiktok_publisher.status import (
                get_status as tiktok_status,
            )
            out["tiktok_ready"] = tiktok_status(
                skip_live=True,
            ).ready
        except Exception:  # noqa: BLE001
            pass
        # Instagram (W963-99 follow-up: Instagram adapter
        # exists + bootstrap registers it; cold-start chain
        # was previously missing the channel-readiness
        # surface for it, so operators using the cold-start
        # orchestrator wouldn't see Instagram in the next-
        # actions list even with credentials missing).
        try:
            from engines.instagram_publisher.status import (
                get_status as instagram_status,
            )
            out["instagram_ready"] = instagram_status(
                skip_live=True,
            ).ready
        except Exception:  # noqa: BLE001
            pass
        return out

    @staticmethod
    def _step_earnings(store_id: Any) -> dict[str, Any]:
        try:
            from engines.earnings_report import (
                EarningsReportEngine,
            )
            payload: dict[str, Any] = {
                "data": {"window_hours": 24.0},
            }
            if store_id:
                payload["data"]["store_id"] = store_id
            result = EarningsReportEngine().run(payload)
            d = result.get("data") or {}
            current = d.get("current") or {}
            return {
                "ok": result.get("status") == "success",
                "verdict": d.get("verdict", "unknown"),
                "revenue_24h": current.get("revenue", 0.0),
                "orders_24h": current.get("order_count", 0),
                "currency": current.get("currency", "USD"),
            }
        except Exception as exc:  # noqa: BLE001
            logger.debug("earnings step raised: %s", exc)
            return {"ok": False, "error": str(exc)[:120]}

    # ── Internal envelope ─────────────────────────────────

    @staticmethod
    def _safe_copy(payload: Any) -> Any:
        if payload is None:
            return {}
        try:
            return copy.deepcopy(payload)
        except Exception as exc:  # noqa: BLE001
            logger.debug("input copy raised: %s", exc)
            return None

    def _success(
        self, data: dict[str, Any], start: float,
    ) -> dict[str, Any]:
        return {
            "status": "success",
            "data": data,
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(),
                ),
                "elapsed_seconds": round(
                    time.monotonic() - start, 3,
                ),
            },
            "error": None,
        }

    def _fail(
        self, reason: str, elapsed: float,
    ) -> dict[str, Any]:
        return {
            "status": "error",
            "data": None,
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(),
                ),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": reason,
        }
