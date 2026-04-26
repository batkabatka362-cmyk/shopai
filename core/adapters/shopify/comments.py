"""ShopifyCommentsAdapter — article comment moderation.

Articles published through the storefront blog can collect reader
comments. Shopify holds new comments in a moderation queue
(``status: PENDING``) until an admin approves them — but for stores
with active blogs, that queue piles up fast. ShopAI's content
engine works the queue automatically:

  * Approve obvious-good comments (positive sentiment, known
    customer email, low spam score).
  * Mark obvious-spam (link blasts, off-topic crypto pitches).
  * Surface ambiguous ones for human review and delete the rest
    once the merchant rules them out.

Capabilities:

  * ``SHOPIFY_LIST_COMMENTS``         — paginated list, optional
    ``status:PENDING`` query filter for queue work.
  * ``SHOPIFY_GET_COMMENT``           — single comment with body,
    author, IP, user agent (the spam-classifier inputs).
  * ``SHOPIFY_APPROVE_COMMENT``       — commentApprove. Pattern A:
    id at field level. Moves PENDING → PUBLISHED.
  * ``SHOPIFY_MARK_COMMENT_SPAM``     — commentSpam. Sends to spam.
  * ``SHOPIFY_MARK_COMMENT_NOT_SPAM`` — commentNotSpam. Pulls back
    out of spam (PENDING).
  * ``SHOPIFY_DELETE_COMMENT``        — commentDelete. Hard-removes
    a comment by GID.

Pattern D: ``CommentSortKeys`` is a NARROW enum — only ``CREATED_AT``
and ``ID``. The wider keys most connections accept all reject.
The adapter exposes only the safe pair.

Pattern F: comment-mutation userErrors HAVE the ``code`` field
(probed live: NOT_FOUND came back on synthetic-id delete).
Selection keeps it.

Pattern E note: gated by ``read_content`` / ``write_content``.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_COMMENT_FIELDS = """
id
status
body
bodyHtml
ip
userAgent
isPublished
createdAt
publishedAt
updatedAt
author {
  name
  email
}
article {
  id
  title
  handle
}
""".strip()


_LIST_COMMENTS_QUERY = f"""
query comments(
  $first: Int!,
  $after: String,
  $query: String,
  $sortKey: CommentSortKeys,
  $reverse: Boolean
) {{
  comments(
    first: $first,
    after: $after,
    query: $query,
    sortKey: $sortKey,
    reverse: $reverse
  ) {{
    pageInfo {{
      hasNextPage
      endCursor
    }}
    edges {{
      node {{
        {_COMMENT_FIELDS}
      }}
    }}
  }}
}}
""".strip()


_GET_COMMENT_QUERY = f"""
query comment($id: ID!) {{
  comment(id: $id) {{
    {_COMMENT_FIELDS}
  }}
}}
""".strip()


def _make_status_change_mutation(
    op_name: str,
) -> str:
    return f"""
mutation {op_name}($id: ID!) {{
  {op_name}(id: $id) {{
    comment {{
      {_COMMENT_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_APPROVE_MUTATION = _make_status_change_mutation("commentApprove")
_SPAM_MUTATION = _make_status_change_mutation("commentSpam")
_NOT_SPAM_MUTATION = _make_status_change_mutation("commentNotSpam")


_DELETE_MUTATION = """
mutation commentDelete($id: ID!) {
  commentDelete(id: $id) {
    deletedCommentId
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


_DEFAULT_LIST_LIMIT = 50
_MAX_LIST_LIMIT = 250

_VALID_SORT_KEYS = {"CREATED_AT", "ID"}


class ShopifyCommentsAdapter(ShopifyBaseAdapter):
    name = "shopify_comments"
    capabilities = {
        Capability.SHOPIFY_LIST_COMMENTS,
        Capability.SHOPIFY_GET_COMMENT,
        Capability.SHOPIFY_APPROVE_COMMENT,
        Capability.SHOPIFY_MARK_COMMENT_SPAM,
        Capability.SHOPIFY_MARK_COMMENT_NOT_SPAM,
        Capability.SHOPIFY_DELETE_COMMENT,
    }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_LIST_COMMENTS:
            return self._list(params)
        if capability == Capability.SHOPIFY_GET_COMMENT:
            return self._get(params)
        if capability == Capability.SHOPIFY_APPROVE_COMMENT:
            return self._status_change(
                params, _APPROVE_MUTATION, "commentApprove",
                Capability.SHOPIFY_APPROVE_COMMENT,
            )
        if capability == Capability.SHOPIFY_MARK_COMMENT_SPAM:
            return self._status_change(
                params, _SPAM_MUTATION, "commentSpam",
                Capability.SHOPIFY_MARK_COMMENT_SPAM,
            )
        if capability == Capability.SHOPIFY_MARK_COMMENT_NOT_SPAM:
            return self._status_change(
                params, _NOT_SPAM_MUTATION, "commentNotSpam",
                Capability.SHOPIFY_MARK_COMMENT_NOT_SPAM,
            )
        if capability == Capability.SHOPIFY_DELETE_COMMENT:
            return self._delete(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── List ───────────────────────────────────────────────────────

    def _list(self, params: dict[str, Any]) -> Any:
        limit = params.get("limit", _DEFAULT_LIST_LIMIT)
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = _DEFAULT_LIST_LIMIT
        limit = max(1, min(limit, _MAX_LIST_LIMIT))

        cursor = params.get("cursor")
        if cursor is not None and not isinstance(cursor, str):
            raise AdapterValidationError(
                self.name, "'cursor' must be a string or None",
            )

        query = params.get("query")
        if query is not None and not isinstance(query, str):
            raise AdapterValidationError(
                self.name, "'query' must be a string or None",
            )

        sort_key = params.get("sort_key") or params.get("sortKey")
        if sort_key is not None:
            if not isinstance(sort_key, str):
                raise AdapterValidationError(
                    self.name, "'sort_key' must be a string",
                )
            sort_key = sort_key.strip().upper()
            if sort_key not in _VALID_SORT_KEYS:
                raise AdapterValidationError(
                    self.name,
                    f"'sort_key' must be one of "
                    f"{sorted(_VALID_SORT_KEYS)}",
                )

        reverse = params.get("reverse")

        data = self._gql(_LIST_COMMENTS_QUERY, {
            "first": limit,
            "after": cursor,
            "query": query,
            "sortKey": sort_key,
            "reverse": bool(reverse) if reverse is not None else None,
        })
        envelope = data.get("comments") or {}
        page_info = envelope.get("pageInfo") or {}
        edges = envelope.get("edges") or []
        comments = [
            self._normalise(edge.get("node") or {})
            for edge in edges if isinstance(edge, dict)
        ]
        return self._success(
            Capability.SHOPIFY_LIST_COMMENTS,
            data={
                "comments": comments,
                "count": len(comments),
                "has_next_page": bool(page_info.get("hasNextPage", False)),
                "end_cursor": page_info.get("endCursor", "") or "",
            },
        )

    # ── Get ────────────────────────────────────────────────────────

    def _get(self, params: dict[str, Any]) -> Any:
        comment_id = self._extract_id(params)
        data = self._gql(_GET_COMMENT_QUERY, {"id": comment_id})
        node = data.get("comment") or {}
        return self._success(
            Capability.SHOPIFY_GET_COMMENT,
            data={
                "comment": self._normalise(node),
                "found": bool(node),
            },
        )

    # ── Status change (approve / spam / not-spam) ──────────────────

    def _status_change(
        self,
        params: dict[str, Any],
        mutation: str,
        op_name: str,
        capability: Capability,
    ) -> Any:
        comment_id = self._extract_id(params)
        data = self._gql(mutation, {"id": comment_id})
        self._check_user_errors(data, op_name)
        payload = data.get(op_name) or {}
        return self._success(
            capability,
            data={
                "comment": self._normalise(
                    payload.get("comment") or {},
                ),
            },
        )

    # ── Delete ─────────────────────────────────────────────────────

    def _delete(self, params: dict[str, Any]) -> Any:
        comment_id = self._extract_id(params)
        data = self._gql(_DELETE_MUTATION, {"id": comment_id})
        self._check_user_errors(data, "commentDelete")
        payload = data.get("commentDelete") or {}
        return self._success(
            Capability.SHOPIFY_DELETE_COMMENT,
            data={
                "deleted_id": payload.get("deletedCommentId", "") or "",
            },
        )

    # ── Helpers ────────────────────────────────────────────────────

    def _extract_id(self, params: dict[str, Any]) -> str:
        comment_id = (
            params.get("id")
            or params.get("comment_id")
            or params.get("commentId")
        )
        if not isinstance(comment_id, str) or not comment_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the comment) is required",
            )
        return comment_id.strip()

    @staticmethod
    def _normalise(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        author = node.get("author") or {}
        article = node.get("article") or {}
        return {
            "id": node.get("id", "") or "",
            "status": node.get("status", "") or "",
            "body": node.get("body", "") or "",
            "body_html": node.get("bodyHtml", "") or "",
            "ip": node.get("ip", "") or "",
            "user_agent": node.get("userAgent", "") or "",
            "is_published": bool(node.get("isPublished", False)),
            "created_at": node.get("createdAt", "") or "",
            "published_at": node.get("publishedAt", "") or "",
            "updated_at": node.get("updatedAt", "") or "",
            "author_name": (
                author.get("name", "")
                if isinstance(author, dict) else ""
            ) or "",
            "author_email": (
                author.get("email", "")
                if isinstance(author, dict) else ""
            ) or "",
            "article_id": (
                article.get("id", "")
                if isinstance(article, dict) else ""
            ) or "",
            "article_title": (
                article.get("title", "")
                if isinstance(article, dict) else ""
            ) or "",
            "article_handle": (
                article.get("handle", "")
                if isinstance(article, dict) else ""
            ) or "",
        }
