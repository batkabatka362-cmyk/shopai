"""ShopifyBlogsAdapter — blog (article-container) CRUD.

The existing ``articles.py`` adapter covers ARTICLE CRUD plus a
LIST_BLOGS read for parent-discovery. The blog write surface —
the *containers* articles live inside — sat outside it. ShopAI's
content engine needs to mint blogs programmatically when:

  * Spinning up a topic-specific blog ("Customer stories",
    "Product updates", "Recipes") that didn't exist on the
    storefront yet.
  * Renaming or re-handling an existing blog as the merchant's
    SEO strategy evolves (with the redirect flags so old article
    URLs don't 404).
  * Cleaning up empty / abandoned blogs after a content
    consolidation pass.

Capabilities:

  * ``SHOPIFY_CREATE_BLOG`` — blogCreate. title required;
    handle, templateSuffix, commentPolicy optional.
  * ``SHOPIFY_UPDATE_BLOG`` — blogUpdate. Pattern A: id at field
    level + BlogUpdateInput. Same fields as create plus the
    redirectNewHandle / redirectArticles flags that handle URL
    migration.
  * ``SHOPIFY_DELETE_BLOG`` — blogDelete. Pattern A: id at field
    level. Returns deletedBlogId.

Friendly call shape::

    {"title":           "Customer stories",
     "handle":          "customer-stories",  # optional, derived
                                              #   from title if omitted
     "comment_policy":  "moderated",  # MODERATED / OPEN / CLOSED
     "template_suffix": "feature"}

UserError type for all three is the standard ``UserError``-with-code
variant (Pattern F: keep code in selection — confirmed live).

Pattern E note: gated by ``write_content`` scope.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_BLOG_FIELDS = """
id
handle
title
templateSuffix
commentPolicy
createdAt
updatedAt
articlesCount {
  count
}
""".strip()


_CREATE_MUTATION = f"""
mutation blogCreate($blog: BlogCreateInput!) {{
  blogCreate(blog: $blog) {{
    blog {{
      {_BLOG_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_UPDATE_MUTATION = f"""
mutation blogUpdate(
  $id: ID!,
  $blog: BlogUpdateInput!
) {{
  blogUpdate(id: $id, blog: $blog) {{
    blog {{
      {_BLOG_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_DELETE_MUTATION = """
mutation blogDelete($id: ID!) {
  blogDelete(id: $id) {
    deletedBlogId
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


_VALID_COMMENT_POLICIES = {"MODERATED", "OPEN", "CLOSED"}


class ShopifyBlogsAdapter(ShopifyBaseAdapter):
    name = "shopify_blogs"
    capabilities = {
        Capability.SHOPIFY_CREATE_BLOG,
        Capability.SHOPIFY_UPDATE_BLOG,
        Capability.SHOPIFY_DELETE_BLOG,
    }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_CREATE_BLOG:
            return self._create(params)
        if capability == Capability.SHOPIFY_UPDATE_BLOG:
            return self._update(params)
        if capability == Capability.SHOPIFY_DELETE_BLOG:
            return self._delete(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Create ─────────────────────────────────────────────────────

    def _create(self, params: dict[str, Any]) -> Any:
        title = params.get("title")
        if not isinstance(title, str) or not title.strip():
            raise AdapterValidationError(
                self.name,
                "'title' is required (the human-readable blog name)",
            )
        body: dict[str, Any] = {"title": title.strip()}
        self._copy_optional_string(params, body, "handle")
        self._copy_optional_string(
            params, body, "template_suffix", "templateSuffix",
        )
        self._copy_comment_policy(params, body)

        data = self._gql(_CREATE_MUTATION, {"blog": body})
        self._check_user_errors(data, "blogCreate")
        payload = data.get("blogCreate") or {}
        return self._success(
            Capability.SHOPIFY_CREATE_BLOG,
            data={
                "blog": self._normalise(payload.get("blog") or {}),
            },
        )

    # ── Update ─────────────────────────────────────────────────────

    def _update(self, params: dict[str, Any]) -> Any:
        blog_id = (
            params.get("id")
            or params.get("blog_id")
            or params.get("blogId")
        )
        if not isinstance(blog_id, str) or not blog_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the blog) is required",
            )

        body: dict[str, Any] = {}
        self._copy_optional_string(params, body, "title")
        self._copy_optional_string(params, body, "handle")
        self._copy_optional_string(
            params, body, "template_suffix", "templateSuffix",
        )
        self._copy_comment_policy(params, body)

        if "redirect_new_handle" in params:
            body["redirectNewHandle"] = bool(params["redirect_new_handle"])
        elif "redirectNewHandle" in params:
            body["redirectNewHandle"] = bool(params["redirectNewHandle"])

        if "redirect_articles" in params:
            body["redirectArticles"] = bool(params["redirect_articles"])
        elif "redirectArticles" in params:
            body["redirectArticles"] = bool(params["redirectArticles"])

        if not body:
            raise AdapterValidationError(
                self.name,
                "supply at least one of: title, handle, "
                "template_suffix, comment_policy, redirect_new_handle, "
                "redirect_articles",
            )

        data = self._gql(_UPDATE_MUTATION, {
            "id": blog_id.strip(), "blog": body,
        })
        self._check_user_errors(data, "blogUpdate")
        payload = data.get("blogUpdate") or {}
        return self._success(
            Capability.SHOPIFY_UPDATE_BLOG,
            data={
                "blog": self._normalise(payload.get("blog") or {}),
            },
        )

    # ── Delete ─────────────────────────────────────────────────────

    def _delete(self, params: dict[str, Any]) -> Any:
        blog_id = (
            params.get("id")
            or params.get("blog_id")
            or params.get("blogId")
        )
        if not isinstance(blog_id, str) or not blog_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the blog) is required",
            )
        data = self._gql(_DELETE_MUTATION, {"id": blog_id.strip()})
        self._check_user_errors(data, "blogDelete")
        payload = data.get("blogDelete") or {}
        return self._success(
            Capability.SHOPIFY_DELETE_BLOG,
            data={
                "deleted_id": payload.get("deletedBlogId", "") or "",
            },
        )

    # ── Helpers ────────────────────────────────────────────────────

    @staticmethod
    def _copy_optional_string(
        params: dict[str, Any],
        dst: dict[str, Any],
        snake_key: str,
        camel_key: str | None = None,
    ) -> None:
        camel_key = camel_key or snake_key
        value = params.get(snake_key)
        if value is None and camel_key != snake_key:
            value = params.get(camel_key)
        if isinstance(value, str) and value.strip():
            dst[camel_key] = value.strip()

    def _copy_comment_policy(
        self, params: dict[str, Any], dst: dict[str, Any],
    ) -> None:
        raw = params.get("comment_policy") or params.get("commentPolicy")
        if raw is None:
            return
        if not isinstance(raw, str):
            raise AdapterValidationError(
                self.name, "'comment_policy' must be a string",
            )
        up = raw.strip().upper()
        if up not in _VALID_COMMENT_POLICIES:
            raise AdapterValidationError(
                self.name,
                f"'comment_policy' must be one of "
                f"{sorted(_VALID_COMMENT_POLICIES)}",
            )
        dst["commentPolicy"] = up

    @staticmethod
    def _normalise(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        articles_count = node.get("articlesCount") or {}
        try:
            count = int(
                articles_count.get("count", 0) or 0
                if isinstance(articles_count, dict) else 0
            )
        except (TypeError, ValueError):
            count = 0
        return {
            "id": node.get("id", "") or "",
            "handle": node.get("handle", "") or "",
            "title": node.get("title", "") or "",
            "template_suffix": node.get("templateSuffix", "") or "",
            "comment_policy": node.get("commentPolicy", "") or "",
            "created_at": node.get("createdAt", "") or "",
            "updated_at": node.get("updatedAt", "") or "",
            "articles_count": count,
        }
