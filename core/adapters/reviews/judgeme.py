"""Judge.me reviews adapter.

Judge.me is the most popular Shopify product-reviews app by a
wide margin, with a permanent free tier and a simple public
REST API. Wave 1 wires it as the first reviews adapter so the
brain can pull UGC for merchandising decisions (featured
review snippets, low-rating product triage, verified-buyer
filtering for homepage carousels, etc.).

Endpoint
--------
``GET https://judge.me/api/v1/reviews``

Auth is by query parameter (``api_token=...``) — Judge.me
deliberately doesn't use a header so shops can paste the
token into lightweight no-code tools. We preserve that shape
but keep the token in the adapter config (never in per-call
params) so it never leaks to logs or per-tenant state.

Pagination
----------
Judge.me uses ``page`` / ``per_page``. The API caps
``per_page`` at 100, which our base class also enforces via
the shared validator.

Pricing
-------
Judge.me's free tier includes unlimited reviews and API
access. Per-call cost is $0. Premium plans add features but
not per-call pricing, so ``cost_per_call = 0.0`` is accurate
for every operator.

Reference: https://judge.me/api/docs
"""
from __future__ import annotations

from typing import Any

from ..errors import AdapterError
from ._base import ReviewsBaseAdapter


class JudgeMeAdapter(ReviewsBaseAdapter):
    """Judge.me — Shopify product reviews."""

    name = "judgeme"
    base_url = "https://judge.me"
    config_alias = "judgeme"
    priority = 80

    # Free tier covers every operator; subclasses can override
    # if a premium tier starts charging per call.
    cost_per_call: float = 0.0

    # ── URL + auth ────────────────────────────────────────────

    def _fetch_url(self) -> str:
        return f"{self.base_url}/api/v1/reviews"

    def _auth_params(self) -> list[tuple[str, str]]:
        """Judge.me authenticates via ``api_token=<token>``."""
        return [("api_token", self._api_key())]

    def _auth_headers(self) -> dict[str, str]:
        return {"Accept": "application/json"}

    # ── Query params ──────────────────────────────────────────

    def _build_fetch_params(
        self, params: dict[str, Any],
    ) -> list[tuple[str, str]]:
        query: list[tuple[str, str]] = [
            ("shop_domain", str(params["shop_domain"])),
        ]

        product_id = params.get("product_id")
        if product_id is not None and product_id != "":
            query.append(("product_id", str(product_id)))

        product_handle = params.get("product_handle")
        if product_handle:
            query.append(("product_handle", str(product_handle)))

        per_page = params.get("per_page")
        if per_page is not None:
            query.append(("per_page", str(int(per_page))))

        page = params.get("page")
        if page is not None:
            query.append(("page", str(int(page))))

        rating_min = params.get("rating_min")
        if rating_min is not None:
            # Judge.me's public API doesn't support a server-side
            # minimum-rating filter, so we forward it as a hint
            # in the query (noop for Judge.me, honoured by any
            # vendor that supports it) AND post-filter the
            # response after parsing. This keeps the normalised
            # contract ("rating_min returns only matching
            # reviews") honest regardless of vendor support.
            query.append(("rating", str(int(rating_min))))

        verified_only = params.get("verified_only")
        if verified_only is not None:
            query.append(
                ("verified", "buyer" if verified_only else ""),
            )

        return query

    # ── Response ──────────────────────────────────────────────

    def _parse_fetch_response(
        self, raw: Any, params: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise AdapterError(
                self.name,
                f"unexpected Judge.me response type: "
                f"{type(raw).__name__}",
            )

        items = raw.get("reviews")
        if not isinstance(items, list):
            raise AdapterError(
                self.name,
                "Judge.me response missing 'reviews' list",
            )

        rating_min = params.get("rating_min")
        try:
            rating_min_int = (
                int(rating_min) if rating_min is not None else None
            )
        except (TypeError, ValueError):
            rating_min_int = None

        verified_only = bool(params.get("verified_only"))

        reviews: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue

            rating = self._safe_int(item.get("rating"))
            if rating_min_int is not None and rating < rating_min_int:
                continue

            verified_flag = self._is_verified(item.get("verified"))
            if verified_only and not verified_flag:
                continue

            reviewer = item.get("reviewer") or {}
            reviewer_name = ""
            if isinstance(reviewer, dict):
                reviewer_name = str(
                    reviewer.get("name")
                    or reviewer.get("email")
                    or "",
                )

            reviews.append(
                {
                    "id":            str(item.get("id", "") or ""),
                    "rating":        rating,
                    "title":         str(item.get("title", "") or ""),
                    "body":          str(item.get("body", "") or ""),
                    "reviewer_name": reviewer_name,
                    "verified":      verified_flag,
                    "created_at":    str(
                        item.get("created_at", "") or "",
                    ),
                    "product_id":    str(
                        item.get("product_external_id")
                        or item.get("product_id")
                        or "",
                    ),
                },
            )

        page_val = self._safe_int(raw.get("current_page") or raw.get("page"))
        per_page_val = self._safe_int(raw.get("per_page"))

        return {
            "reviews":  reviews,
            "page":     page_val or int(params.get("page") or 1),
            "per_page": per_page_val or int(
                params.get("per_page") or len(reviews),
            ),
            "count":    len(reviews),
        }

    # ── Helpers ───────────────────────────────────────────────

    @staticmethod
    def _safe_int(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _is_verified(value: Any) -> bool:
        """Judge.me returns one of ``"buyer"``, ``"unverified"``,
        or a boolean. Normalise to a single bool."""
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("buyer", "verified", "true", "1")
        return False
