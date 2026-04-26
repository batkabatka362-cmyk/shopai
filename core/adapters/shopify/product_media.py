"""ShopifyProductMediaAdapter — product / variant media wiring.

Companions:
  * ``files.py`` covers fileCreate (URL + staged uploads) +
    fileList. Once a media node exists at the shop level, it
    needs to be wired to specific products / variants.
  * ``products.py`` handles product CRUD but the variant-level
    media attach/detach + product-level media reorder live on
    separate mutations.

This adapter ships those wiring primitives, used by ShopAI's
creative engine after it generates new media:

  * **Variant-specific imagery.** When a new variant ships
    ("blue" + "red" of the same SKU), the creative engine
    appends the colour-specific media to each variant. Without
    this, every variant fall back to the product hero image.
  * **Hero rotation.** Pricing engine promotes a winning image
    by reordering it to position 0 in the product gallery.
  * **Cleanup after variant retire.** When a variant is dropped,
    detach its media so it doesn't linger orphaned.

Capabilities:

  * ``SHOPIFY_REORDER_PRODUCT_MEDIA``  — productReorderMedia.
    Pattern A: id + moves at field level.
  * ``SHOPIFY_APPEND_VARIANT_MEDIA``   — productVariantAppendMedia.
    Pattern A: productId + variantMedia at field level.
  * ``SHOPIFY_DETACH_VARIANT_MEDIA``   — productVariantDetachMedia.
    Pattern A: productId + variantMedia at field level.

Pattern D (codified): ``productReorderMedia`` returns
``mediaUserErrors`` (NOT the standard ``userErrors`` key) of
type ``MediaUserError`` (has ``code``). Same shape as
``orderCancel``'s ``orderCancelUserErrors``. The base
``_check_user_errors`` helper looks for the literal
``userErrors`` key, so the adapter pulls the custom key
manually.

The other two mutations use the standard ``userErrors`` of
type ``MediaUserError`` (has ``code``).
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_PRODUCT_FIELDS = """
id
handle
title
""".strip()


_VARIANT_FIELDS = """
id
title
""".strip()


_REORDER_MEDIA_MUTATION = """
mutation productReorderMedia($id: ID!, $moves: [MoveInput!]!) {
  productReorderMedia(id: $id, moves: $moves) {
    job {
      id
      done
    }
    mediaUserErrors {
      field
      message
      code
    }
  }
}
""".strip()


_APPEND_VARIANT_MEDIA_MUTATION = f"""
mutation productVariantAppendMedia(
  $productId: ID!,
  $variantMedia: [ProductVariantAppendMediaInput!]!
) {{
  productVariantAppendMedia(
    productId: $productId,
    variantMedia: $variantMedia
  ) {{
    product {{
      {_PRODUCT_FIELDS}
    }}
    productVariants {{
      {_VARIANT_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_DETACH_VARIANT_MEDIA_MUTATION = f"""
mutation productVariantDetachMedia(
  $productId: ID!,
  $variantMedia: [ProductVariantDetachMediaInput!]!
) {{
  productVariantDetachMedia(
    productId: $productId,
    variantMedia: $variantMedia
  ) {{
    product {{
      {_PRODUCT_FIELDS}
    }}
    productVariants {{
      {_VARIANT_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


class ShopifyProductMediaAdapter(ShopifyBaseAdapter):
    name = "shopify_product_media"
    capabilities = {
        Capability.SHOPIFY_REORDER_PRODUCT_MEDIA,
        Capability.SHOPIFY_APPEND_VARIANT_MEDIA,
        Capability.SHOPIFY_DETACH_VARIANT_MEDIA,
    }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_REORDER_PRODUCT_MEDIA:
            return self._reorder(params)
        if capability == Capability.SHOPIFY_APPEND_VARIANT_MEDIA:
            return self._append(params)
        if capability == Capability.SHOPIFY_DETACH_VARIANT_MEDIA:
            return self._detach(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Reorder ────────────────────────────────────────────────────

    def _reorder(self, params: dict[str, Any]) -> Any:
        product_id = self._extract_product_id(params)
        moves = self._build_moves(params.get("moves"))
        data = self._gql(_REORDER_MEDIA_MUTATION, {
            "id": product_id, "moves": moves,
        })
        # Pattern D: productReorderMedia uses mediaUserErrors,
        # NOT userErrors. The base helper looks for the literal
        # userErrors key, so check the custom key manually.
        payload = data.get("productReorderMedia") or {}
        errors = payload.get("mediaUserErrors") or []
        if errors:
            messages = []
            for e in errors:
                if isinstance(e, dict):
                    field = ".".join(e.get("field", []) or [])
                    msg = e.get("message", "")
                    messages.append(
                        f"{field}: {msg}" if field else msg,
                    )
            raise AdapterValidationError(
                self.name,
                f"productReorderMedia mediaUserErrors: "
                f"{'; '.join(messages)[:300]}",
            )

        job = payload.get("job") or {}
        return self._success(
            Capability.SHOPIFY_REORDER_PRODUCT_MEDIA,
            data={
                "job_id": (
                    job.get("id", "") if isinstance(job, dict) else ""
                ) or "",
                "job_done": bool(
                    job.get("done", False) if isinstance(job, dict) else False
                ),
                "moves_count": len(moves),
            },
        )

    # ── Append variant media ───────────────────────────────────────

    def _append(self, params: dict[str, Any]) -> Any:
        product_id = self._extract_product_id(params)
        variant_media = self._build_variant_media(
            params.get("variant_media"), label="variant_media",
        )
        data = self._gql(_APPEND_VARIANT_MEDIA_MUTATION, {
            "productId": product_id, "variantMedia": variant_media,
        })
        self._check_user_errors(data, "productVariantAppendMedia")
        payload = data.get("productVariantAppendMedia") or {}
        return self._success(
            Capability.SHOPIFY_APPEND_VARIANT_MEDIA,
            data={
                "product": self._normalise_product(
                    payload.get("product") or {}
                ),
                "variants_count": len(payload.get("productVariants") or []),
                "appended_count": len(variant_media),
            },
        )

    # ── Detach variant media ───────────────────────────────────────

    def _detach(self, params: dict[str, Any]) -> Any:
        product_id = self._extract_product_id(params)
        variant_media = self._build_variant_media(
            params.get("variant_media"), label="variant_media",
        )
        data = self._gql(_DETACH_VARIANT_MEDIA_MUTATION, {
            "productId": product_id, "variantMedia": variant_media,
        })
        self._check_user_errors(data, "productVariantDetachMedia")
        payload = data.get("productVariantDetachMedia") or {}
        return self._success(
            Capability.SHOPIFY_DETACH_VARIANT_MEDIA,
            data={
                "product": self._normalise_product(
                    payload.get("product") or {}
                ),
                "variants_count": len(payload.get("productVariants") or []),
                "detached_count": len(variant_media),
            },
        )

    # ── Helpers ────────────────────────────────────────────────────

    def _extract_product_id(self, params: dict[str, Any]) -> str:
        product_id = (
            params.get("id")
            or params.get("product_id")
            or params.get("productId")
        )
        if not isinstance(product_id, str) or not product_id.strip():
            raise AdapterValidationError(
                self.name,
                "'product_id' (Shopify GID for the product) is required",
            )
        return product_id.strip()

    def _build_moves(self, raw: Any) -> list[dict[str, Any]]:
        if not isinstance(raw, list) or not raw:
            raise AdapterValidationError(
                self.name,
                "'moves' must be a non-empty list of "
                "{id, new_position} dicts",
            )
        out: list[dict[str, Any]] = []
        for i, m in enumerate(raw):
            if not isinstance(m, dict):
                raise AdapterValidationError(
                    self.name, f"moves[{i}] must be a dict",
                )
            mid = m.get("id") or m.get("media_id")
            new_pos = (
                m.get("new_position")
                if "new_position" in m else m.get("newPosition")
            )
            if not isinstance(mid, str) or not mid.strip():
                raise AdapterValidationError(
                    self.name,
                    f"moves[{i}] missing 'id' (media GID)",
                )
            if new_pos is None:
                raise AdapterValidationError(
                    self.name,
                    f"moves[{i}] missing 'new_position' "
                    "(zero-indexed int)",
                )
            try:
                pos_int = int(new_pos)
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    self.name,
                    f"moves[{i}].new_position must be a non-negative int",
                ) from exc
            if pos_int < 0:
                raise AdapterValidationError(
                    self.name,
                    f"moves[{i}].new_position must be >= 0",
                )
            out.append({
                "id": mid.strip(),
                "newPosition": str(pos_int),
            })
        return out

    def _build_variant_media(
        self, raw: Any, *, label: str,
    ) -> list[dict[str, Any]]:
        if not isinstance(raw, list) or not raw:
            raise AdapterValidationError(
                self.name,
                f"'{label}' must be a non-empty list of "
                "{variant_id, media_ids} dicts",
            )
        out: list[dict[str, Any]] = []
        for i, m in enumerate(raw):
            if not isinstance(m, dict):
                raise AdapterValidationError(
                    self.name, f"{label}[{i}] must be a dict",
                )
            variant_id = m.get("variant_id") or m.get("variantId")
            media_ids = m.get("media_ids") or m.get("mediaIds")
            if not isinstance(variant_id, str) or not variant_id.strip():
                raise AdapterValidationError(
                    self.name,
                    f"{label}[{i}] missing 'variant_id' (variant GID)",
                )
            if isinstance(media_ids, str):
                media_ids = [media_ids]
            if not isinstance(media_ids, list) or not media_ids:
                raise AdapterValidationError(
                    self.name,
                    f"{label}[{i}] 'media_ids' must be a non-empty list",
                )
            if not all(isinstance(mid, str) for mid in media_ids):
                raise AdapterValidationError(
                    self.name,
                    f"{label}[{i}].media_ids must contain only GID strings",
                )
            cleaned = [mid.strip() for mid in media_ids if mid.strip()]
            if not cleaned:
                raise AdapterValidationError(
                    self.name,
                    f"{label}[{i}].media_ids contained only blanks",
                )
            out.append({
                "variantId": variant_id.strip(),
                "mediaIds": cleaned,
            })
        return out

    @staticmethod
    def _normalise_product(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        return {
            "id": node.get("id", "") or "",
            "handle": node.get("handle", "") or "",
            "title": node.get("title", "") or "",
        }
