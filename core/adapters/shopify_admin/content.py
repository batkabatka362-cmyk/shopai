"""Shopify content — blogs + articles + pages.

Previously scattered across ``execution/store_configurator``
(``_setup_pages`` / ``_setup_blog``) as one-shot bootstrap
code. This module is the unified REST surface so engines
beyond the configurator can write content (content_generator
for daily blog posts, seo engine for SEO-optimised articles,
the publisher for "about" page updates on rebrand, etc.).

Resources:

  * **Blog** — a grouping of articles (default: "News"). A
    store has 1+ blogs; each blog has its own RSS feed and
    navigation entry.
  * **Article** — a post under a blog. Has title, body_html,
    author, tags, optional image, SEO fields via metafields.
  * **Page** — standalone static content (About, Contact,
    FAQ). No RSS, no blog grouping.

Pages live alongside blogs/articles because they share the
same authoring semantics and the same REST shape envelope
pattern, and engines touching content routinely write all
three in one flow ("seed welcome article + about page").

REST endpoints:

  * ``/blogs.json``                            — blogs CRUD
  * ``/blogs/{blog_id}/articles.json``         — articles CRUD
  * ``/articles.json``                         — cross-blog
                                                 list
  * ``/pages.json``                            — pages CRUD
"""
from __future__ import annotations

import logging
from typing import Any

from core.adapters.shopify_admin.client import (
    ShopifyAdminClient, ShopifyAdminError,
)

_logger = logging.getLogger("shopai.shopify_admin.content")


class Blogs:
    """Blog containers (one per topic area)."""

    @staticmethod
    def list_blogs(
        client: ShopifyAdminClient,
        *,
        limit: int = 50,
        handle: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "limit": max(1, min(int(limit), 250)),
        }
        if handle:
            params["handle"] = str(handle)
        result = client.get("blogs.json", params=params)
        rows = result.get("blogs") or []
        return [r for r in rows if isinstance(r, dict)]

    @staticmethod
    def get(
        client: ShopifyAdminClient, blog_id: int | str,
    ) -> dict[str, Any]:
        result = client.get(f"blogs/{blog_id}.json")
        blog = result.get("blog")
        if not isinstance(blog, dict):
            raise ShopifyAdminError(
                f"blog {blog_id} not returned",
                path=f"blogs/{blog_id}.json",
            )
        return blog

    @staticmethod
    def find_by_handle(
        client: ShopifyAdminClient, handle: str,
    ) -> dict[str, Any] | None:
        """Convenience — return the first blog matching the
        handle (Shopify allows unique handles). None when no
        blog matches."""
        if not handle:
            raise ValueError("handle: required")
        for blog in Blogs.list_blogs(client, handle=handle):
            if str(blog.get("handle") or "") == handle:
                return blog
        return None

    @staticmethod
    def create(
        client: ShopifyAdminClient,
        *,
        title: str,
        handle: str | None = None,
        commentable: str = "no",
        feedburner: str | None = None,
        tags: str | None = None,
        template_suffix: str | None = None,
    ) -> dict[str, Any]:
        if not title:
            raise ValueError("title: required")
        if commentable not in ("no", "moderate", "yes"):
            raise ValueError(
                "commentable must be 'no', 'moderate', or "
                "'yes'",
            )
        blog: dict[str, Any] = {
            "title": title,
            "commentable": commentable,
        }
        if handle:
            blog["handle"] = str(handle)
        if feedburner:
            blog["feedburner"] = str(feedburner)
        if tags:
            blog["tags"] = str(tags)
        if template_suffix:
            blog["template_suffix"] = str(template_suffix)
        result = client.post("blogs.json", {"blog": blog})
        created = result.get("blog")
        if not isinstance(created, dict):
            raise ShopifyAdminError(
                "blog not returned by create",
                path="blogs.json",
                body=str(result),
            )
        return created

    @staticmethod
    def update(
        client: ShopifyAdminClient,
        blog_id: int | str,
        *,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        if not fields:
            raise ValueError("fields: non-empty dict required")
        result = client.put(
            f"blogs/{blog_id}.json",
            {"blog": {"id": int(blog_id), **fields}},
        )
        updated = result.get("blog")
        if not isinstance(updated, dict):
            raise ShopifyAdminError(
                "blog not returned by update",
                path=f"blogs/{blog_id}.json",
            )
        return updated

    @staticmethod
    def delete(
        client: ShopifyAdminClient, blog_id: int | str,
    ) -> None:
        client.delete(f"blogs/{blog_id}.json")


class Articles:
    """Blog-post CRUD + tag helpers."""

    @staticmethod
    def list_articles(
        client: ShopifyAdminClient,
        *,
        blog_id: int | str | None = None,
        limit: int = 50,
        published_status: str | None = None,
        author: str | None = None,
        tag: str | None = None,
    ) -> list[dict[str, Any]]:
        """List articles. ``blog_id`` filters to one blog;
        omitting it returns across-blog results."""
        params: dict[str, Any] = {
            "limit": max(1, min(int(limit), 250)),
        }
        if published_status:
            params["published_status"] = str(published_status)
        if author:
            params["author"] = str(author)
        if tag:
            params["tag"] = str(tag)
        path = (
            f"blogs/{blog_id}/articles.json"
            if blog_id is not None
            else "articles.json"
        )
        result = client.get(path, params=params)
        rows = result.get("articles") or []
        return [r for r in rows if isinstance(r, dict)]

    @staticmethod
    def get(
        client: ShopifyAdminClient,
        *,
        blog_id: int | str,
        article_id: int | str,
    ) -> dict[str, Any]:
        result = client.get(
            f"blogs/{blog_id}/articles/{article_id}.json",
        )
        art = result.get("article")
        if not isinstance(art, dict):
            raise ShopifyAdminError(
                f"article {article_id} not returned",
                path=(
                    f"blogs/{blog_id}/articles/"
                    f"{article_id}.json"
                ),
            )
        return art

    @staticmethod
    def create(
        client: ShopifyAdminClient,
        *,
        blog_id: int | str,
        title: str,
        body_html: str,
        author: str,
        tags: str | list[str] | None = None,
        handle: str | None = None,
        summary_html: str | None = None,
        published: bool = True,
        image_src: str | None = None,
        image_alt: str | None = None,
        template_suffix: str | None = None,
        metafields: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Create an article under a blog.

        ``tags`` — list or comma-separated string. Shopify
        stores tags as a comma-delimited string internally;
        we normalise both shapes.
        ``image_src`` — optional feature image URL. Pair with
        ``image_alt`` for accessibility + SEO.
        """
        for name, value in (
            ("title", title),
            ("body_html", body_html),
            ("author", author),
        ):
            if not value:
                raise ValueError(f"{name}: required")
        article: dict[str, Any] = {
            "title": title,
            "body_html": body_html,
            "author": author,
            "published": bool(published),
        }
        if tags is not None:
            if isinstance(tags, list):
                article["tags"] = ", ".join(
                    str(t).strip() for t in tags if t
                )
            else:
                article["tags"] = str(tags)
        if handle:
            article["handle"] = str(handle)
        if summary_html:
            article["summary_html"] = str(summary_html)
        if image_src:
            article["image"] = {"src": str(image_src)}
            if image_alt:
                article["image"]["alt"] = str(image_alt)
        if template_suffix:
            article["template_suffix"] = str(template_suffix)
        if metafields:
            article["metafields"] = [
                m for m in metafields if isinstance(m, dict)
            ]
        result = client.post(
            f"blogs/{blog_id}/articles.json",
            {"article": article},
        )
        created = result.get("article")
        if not isinstance(created, dict):
            raise ShopifyAdminError(
                "article not returned by create",
                path=f"blogs/{blog_id}/articles.json",
                body=str(result),
            )
        return created

    @staticmethod
    def update(
        client: ShopifyAdminClient,
        *,
        blog_id: int | str,
        article_id: int | str,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        if not fields:
            raise ValueError("fields: non-empty dict required")
        result = client.put(
            f"blogs/{blog_id}/articles/{article_id}.json",
            {"article": {
                "id": int(article_id), **fields,
            }},
        )
        updated = result.get("article")
        if not isinstance(updated, dict):
            raise ShopifyAdminError(
                "article not returned by update",
                path=(
                    f"blogs/{blog_id}/articles/"
                    f"{article_id}.json"
                ),
            )
        return updated

    @staticmethod
    def delete(
        client: ShopifyAdminClient,
        *,
        blog_id: int | str,
        article_id: int | str,
    ) -> None:
        client.delete(
            f"blogs/{blog_id}/articles/{article_id}.json",
        )

    @staticmethod
    def publish(
        client: ShopifyAdminClient,
        *,
        blog_id: int | str,
        article_id: int | str,
    ) -> dict[str, Any]:
        """Toggle published=true. §4b.D idempotent."""
        return Articles.update(
            client,
            blog_id=blog_id,
            article_id=article_id,
            fields={"published": True},
        )

    @staticmethod
    def unpublish(
        client: ShopifyAdminClient,
        *,
        blog_id: int | str,
        article_id: int | str,
    ) -> dict[str, Any]:
        return Articles.update(
            client,
            blog_id=blog_id,
            article_id=article_id,
            fields={"published": False},
        )


class Pages:
    """Standalone static pages (About / Contact / FAQ)."""

    @staticmethod
    def list_pages(
        client: ShopifyAdminClient,
        *,
        limit: int = 50,
        handle: str | None = None,
        published_status: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "limit": max(1, min(int(limit), 250)),
        }
        if handle:
            params["handle"] = str(handle)
        if published_status:
            params["published_status"] = str(published_status)
        result = client.get("pages.json", params=params)
        rows = result.get("pages") or []
        return [r for r in rows if isinstance(r, dict)]

    @staticmethod
    def get(
        client: ShopifyAdminClient, page_id: int | str,
    ) -> dict[str, Any]:
        result = client.get(f"pages/{page_id}.json")
        page = result.get("page")
        if not isinstance(page, dict):
            raise ShopifyAdminError(
                f"page {page_id} not returned",
                path=f"pages/{page_id}.json",
            )
        return page

    @staticmethod
    def find_by_handle(
        client: ShopifyAdminClient, handle: str,
    ) -> dict[str, Any] | None:
        if not handle:
            raise ValueError("handle: required")
        for page in Pages.list_pages(client, handle=handle):
            if str(page.get("handle") or "") == handle:
                return page
        return None

    @staticmethod
    def create(
        client: ShopifyAdminClient,
        *,
        title: str,
        body_html: str,
        handle: str | None = None,
        published: bool = True,
        author: str | None = None,
        template_suffix: str | None = None,
        metafields: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if not title:
            raise ValueError("title: required")
        if not body_html:
            raise ValueError("body_html: required")
        page: dict[str, Any] = {
            "title": title,
            "body_html": body_html,
            "published": bool(published),
        }
        if handle:
            page["handle"] = str(handle)
        if author:
            page["author"] = str(author)
        if template_suffix:
            page["template_suffix"] = str(template_suffix)
        if metafields:
            page["metafields"] = [
                m for m in metafields if isinstance(m, dict)
            ]
        result = client.post("pages.json", {"page": page})
        created = result.get("page")
        if not isinstance(created, dict):
            raise ShopifyAdminError(
                "page not returned by create",
                path="pages.json",
                body=str(result),
            )
        return created

    @staticmethod
    def update(
        client: ShopifyAdminClient,
        page_id: int | str,
        *,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        if not fields:
            raise ValueError("fields: non-empty dict required")
        result = client.put(
            f"pages/{page_id}.json",
            {"page": {"id": int(page_id), **fields}},
        )
        updated = result.get("page")
        if not isinstance(updated, dict):
            raise ShopifyAdminError(
                "page not returned by update",
                path=f"pages/{page_id}.json",
            )
        return updated

    @staticmethod
    def delete(
        client: ShopifyAdminClient, page_id: int | str,
    ) -> None:
        client.delete(f"pages/{page_id}.json")


class ArticleComments:
    """Shopify blog article comments (moderation surface).

    Comments move through a state machine:
      unapproved → (approved | spam | removed)

    ``approved`` shows on the storefront; ``spam`` is
    quarantined; ``removed`` is soft-deleted but kept for
    audit. This class exposes the moderation verbs every
    content platform needs — read / approve / spam / restore
    / remove.
    """

    _STATUS = {"approved", "unapproved", "spam", "removed"}

    @staticmethod
    def list_comments(
        client: ShopifyAdminClient,
        *,
        status: str | None = None,
        limit: int = 50,
        article_id: int | str | None = None,
    ) -> list[dict[str, Any]]:
        if status is not None and status not in (
            ArticleComments._STATUS
        ):
            raise ValueError(
                f"status must be one of "
                f"{sorted(ArticleComments._STATUS)}",
            )
        params: dict[str, Any] = {
            "limit": max(1, min(int(limit), 250)),
        }
        if status:
            params["status"] = status
        if article_id is not None:
            params["article_id"] = int(article_id)
        result = client.get(
            "comments.json", params=params,
        )
        rows = result.get("comments") or []
        return [r for r in rows if isinstance(r, dict)]

    @staticmethod
    def get(
        client: ShopifyAdminClient,
        comment_id: int | str,
    ) -> dict[str, Any]:
        result = client.get(
            f"comments/{comment_id}.json",
        )
        comment = result.get("comment")
        if not isinstance(comment, dict):
            raise ShopifyAdminError(
                f"comment {comment_id} not returned",
                path=f"comments/{comment_id}.json",
            )
        return comment

    @staticmethod
    def approve(
        client: ShopifyAdminClient,
        comment_id: int | str,
    ) -> dict[str, Any]:
        return ArticleComments._transition(
            client, comment_id, "approve",
        )

    @staticmethod
    def mark_spam(
        client: ShopifyAdminClient,
        comment_id: int | str,
    ) -> dict[str, Any]:
        return ArticleComments._transition(
            client, comment_id, "spam",
        )

    @staticmethod
    def restore(
        client: ShopifyAdminClient,
        comment_id: int | str,
    ) -> dict[str, Any]:
        """Move a spam/removed comment back to unapproved
        for fresh moderation."""
        return ArticleComments._transition(
            client, comment_id, "restore",
        )

    @staticmethod
    def remove(
        client: ShopifyAdminClient,
        comment_id: int | str,
    ) -> dict[str, Any]:
        return ArticleComments._transition(
            client, comment_id, "remove",
        )

    @staticmethod
    def _transition(
        client: ShopifyAdminClient,
        comment_id: int | str,
        verb: str,
    ) -> dict[str, Any]:
        if verb not in (
            "approve", "spam", "restore", "remove",
        ):
            raise ValueError(
                f"unsupported transition: {verb}",
            )
        result = client.post(
            f"comments/{comment_id}/{verb}.json", {},
        )
        comment = result.get("comment")
        if not isinstance(comment, dict):
            raise ShopifyAdminError(
                f"comment not returned by {verb}",
                path=f"comments/{comment_id}/{verb}.json",
            )
        return comment
