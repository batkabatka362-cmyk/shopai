"""ContentPublisher — publishes content to Shopify and social platforms.

Uses only the Python standard library (urllib.request).
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Any

# In-memory store for scheduled jobs (flushed to ContentScheduler when available)
_SCHEDULE_STORE: dict[str, dict[str, Any]] = {}


class ContentPublisher:
    """Publishes blog posts/pages to Shopify and content to social platforms."""

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def publish_to_shopify(
        self,
        shop_url: str,
        api_key: str,
        content: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a blog post or page on a Shopify store.

        Args:
            shop_url: e.g. ``"mystore.myshopify.com"``
            api_key:  Shopify Admin API access token.
            content:  Dict with at minimum ``title`` and ``body_html``.
                      Optional ``type`` key (``"article"`` or ``"page"``,
                      default ``"article"``), ``blog_id`` for articles.

        Returns:
            ``{"status": "published", "platform": "shopify",
               "content_id": str, "url": str, "raw": {...}}``
        """
        errors = self._validate_content(content)
        if errors:
            return {"status": "error", "errors": errors, "platform": "shopify"}

        content_type = content.get("type", "article")
        formatted = self._format_for_platform("shopify", content)
        headers = {
            "X-Shopify-Access-Token": api_key,
            "Accept": "application/json",
        }

        if content_type == "page":
            url = self._build_url(shop_url, "/admin/api/2024-01/pages.json")
            payload = {"page": formatted}
            key = "page"
        else:
            blog_id = content.get("blog_id", "")
            if not blog_id:
                # Auto-fetch or create the default blog
                blog_id = self._get_or_create_blog(shop_url, api_key, headers)
            url = self._build_url(
                shop_url, f"/admin/api/2024-01/blogs/{blog_id}/articles.json"
            )
            payload = {"article": formatted}
            key = "article"

        try:
            response = self._make_request("POST", url, headers, payload)
            resource = response.get(key, response)
            return {
                "status": "published",
                "platform": "shopify",
                "content_id": str(resource.get("id", "")),
                "url": resource.get("url", ""),
                "raw": resource,
            }
        except Exception as exc:
            return {"status": "error", "platform": "shopify", "error": str(exc)}

    def publish_to_social(
        self,
        platform: str,
        credentials: dict[str, Any],
        content: dict[str, Any],
    ) -> dict[str, Any]:
        """Publish content to a social media platform.

        Supported platforms: ``facebook``, ``instagram``, ``twitter``,
        ``linkedin``, ``tiktok``.

        Returns:
            ``{"status": "published", "platform": str,
               "content_id": str, "created_at": str}``
        """
        errors = self._validate_content(content)
        if errors:
            return {"status": "error", "errors": errors, "platform": platform}

        formatted = self._format_for_platform(platform, content)
        now = datetime.now(timezone.utc).isoformat()

        try:
            raw = self._post_to_social(platform, credentials, formatted)
            content_id = self._extract_post_id(platform, raw)
            return {
                "status": "published",
                "platform": platform,
                "content_id": content_id,
                "created_at": now,
                "raw": raw,
            }
        except Exception as exc:
            return {"status": "error", "platform": platform, "error": str(exc)}

    def schedule_publish(
        self,
        content: dict[str, Any],
        publish_at: str,
        platform: str,
    ) -> dict[str, Any]:
        """Register a content item for future publication.

        Delegates to ContentScheduler if importable; falls back to the
        module-level ``_SCHEDULE_STORE`` dict.

        Args:
            content:    Content dict to publish later.
            publish_at: ISO-8601 datetime string (e.g. ``"2024-06-01T09:00:00Z"``).
            platform:   Target platform string.

        Returns:
            ``{"job_id": str, "status": "scheduled",
               "publish_at": str, "platform": str}``
        """
        errors = self._validate_content(content)
        if errors:
            return {"status": "error", "errors": errors}

        try:
            from execution.content.scheduler import ContentScheduler
            scheduler = ContentScheduler()
            job_id = scheduler.schedule(
                content_id=content.get("id", str(uuid.uuid4())),
                publish_at=publish_at,
                platform=platform,
                job_config={"content": content},
            )
        except Exception:
            job_id = str(uuid.uuid4())
            _SCHEDULE_STORE[job_id] = {
                "job_id": job_id,
                "content": content,
                "publish_at": publish_at,
                "platform": platform,
                "status": "scheduled",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }

        return {
            "job_id": job_id,
            "status": "scheduled",
            "publish_at": publish_at,
            "platform": platform,
        }

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    def _format_for_platform(
        self, platform: str, content: dict[str, Any]
    ) -> dict[str, Any]:
        """Return a platform-specific payload dict for *content*."""
        if platform == "shopify":
            return {
                "title": content.get("title", ""),
                "body_html": content.get("body_html", content.get("body", "")),
                "author": content.get("author", ""),
                "tags": content.get("tags", ""),
                "summary_html": content.get("summary", ""),
                "published": content.get("published", True),
                "image": content.get("image"),
            }

        if platform in ("facebook", "instagram"):
            message = content.get("caption", content.get("body", content.get("title", "")))
            payload: dict[str, Any] = {"message": message}
            if "image_url" in content:
                payload["url"] = content["image_url"]
            if "link" in content:
                payload["link"] = content["link"]
            return payload

        if platform == "twitter":
            text = content.get("tweet", content.get("body", content.get("title", "")))
            return {"text": str(text)[:280]}

        if platform == "linkedin":
            return {
                "text": content.get("body", content.get("title", "")),
                "title": content.get("title", ""),
                "description": content.get("summary", ""),
                "visibility": content.get("visibility", "PUBLIC"),
            }

        if platform == "tiktok":
            return {
                "video_url": content.get("video_url", ""),
                "description": content.get(
                    "caption", content.get("body", content.get("title", ""))
                ),
                "privacy_level": content.get("privacy_level", "PUBLIC_TO_EVERYONE"),
            }

        # Generic fallback
        return dict(content)

    def _validate_content(self, content: dict[str, Any]) -> list[str]:
        """Return validation errors (empty list = valid)."""
        errors: list[str] = []
        if not content:
            errors.append("Content dict is empty.")
            return errors
        if not content.get("title") and not content.get("body") and not content.get("body_html"):
            errors.append("Content must have at least one of: 'title', 'body', 'body_html'.")
        return errors

    def _post_to_social(
        self,
        platform: str,
        credentials: dict[str, Any],
        formatted: dict[str, Any],
    ) -> dict[str, Any]:
        """Dispatch to the correct social API endpoint."""
        if platform == "facebook":
            page_id = credentials.get("page_id", "me")
            access_token = credentials.get("access_token", "")
            url = f"https://graph.facebook.com/v19.0/{page_id}/feed"
            payload = {**formatted, "access_token": access_token}
            return self._make_request(
                "POST", url, {}, payload, use_form=True
            )

        if platform == "instagram":
            ig_id = credentials.get("instagram_id", "")
            access_token = credentials.get("access_token", "")
            # Step 1: create media container
            create_url = f"https://graph.facebook.com/v19.0/{ig_id}/media"
            container_payload = {
                **formatted,
                "access_token": access_token,
            }
            container = self._make_request(
                "POST", create_url, {}, container_payload, use_form=True
            )
            container_id = container.get("id", "")
            # Step 2: publish
            publish_url = f"https://graph.facebook.com/v19.0/{ig_id}/media_publish"
            publish_payload = {
                "creation_id": container_id,
                "access_token": access_token,
            }
            return self._make_request(
                "POST", publish_url, {}, publish_payload, use_form=True
            )

        if platform == "twitter":
            bearer = credentials.get("bearer_token", "")
            url = "https://api.twitter.com/2/tweets"
            headers = {
                "Authorization": f"Bearer {bearer}",
                "Content-Type": "application/json",
            }
            return self._make_request("POST", url, headers, formatted)

        if platform == "linkedin":
            access_token = credentials.get("access_token", "")
            author = credentials.get("author", "")  # urn:li:person:... or urn:li:organization:...
            url = "https://api.linkedin.com/v2/ugcPosts"
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "X-Restli-Protocol-Version": "2.0.0",
            }
            payload = {
                "author": author,
                "lifecycleState": "PUBLISHED",
                "specificContent": {
                    "com.linkedin.ugc.ShareContent": {
                        "shareCommentary": {"text": formatted.get("text", "")},
                        "shareMediaCategory": "NONE",
                    }
                },
                "visibility": {
                    "com.linkedin.ugc.MemberNetworkVisibility": formatted.get(
                        "visibility", "PUBLIC"
                    )
                },
            }
            return self._make_request("POST", url, headers, payload)

        if platform == "tiktok":
            access_token = credentials.get("access_token", "")
            url = "https://open.tiktokapis.com/v2/post/publish/video/init/"
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json; charset=UTF-8",
            }
            payload = {
                "post_info": {
                    "title": formatted.get("description", ""),
                    "privacy_level": formatted.get("privacy_level", "PUBLIC_TO_EVERYONE"),
                    "disable_duet": False,
                    "disable_comment": False,
                    "disable_stitch": False,
                },
                "source_info": {
                    "source": "PULL_FROM_URL",
                    "video_url": formatted.get("video_url", ""),
                },
            }
            return self._make_request("POST", url, headers, payload)

        raise ValueError(f"Unsupported social platform: {platform!r}")

    def _extract_post_id(self, platform: str, raw: dict[str, Any]) -> str:
        if platform in ("facebook",):
            return str(raw.get("id", ""))
        if platform == "instagram":
            return str(raw.get("id", ""))
        if platform == "twitter":
            return str(raw.get("data", {}).get("id", raw.get("id", "")))
        if platform == "linkedin":
            return str(raw.get("id", ""))
        if platform == "tiktok":
            return str(raw.get("data", {}).get("publish_id", raw.get("id", "")))
        return str(raw.get("id", ""))

    def _get_or_create_blog(
        self,
        shop_url: str,
        api_key: str,
        headers: dict[str, str],
    ) -> str:
        """Fetch the first blog ID on the store, creating one if none exist."""
        list_url = self._build_url(shop_url, "/admin/api/2024-01/blogs.json?limit=1")
        try:
            resp = self._make_request("GET", list_url, headers)
            blogs = resp.get("blogs", [])
            if blogs:
                return str(blogs[0]["id"])
            # Create a default blog
            create_url = self._build_url(shop_url, "/admin/api/2024-01/blogs.json")
            created = self._make_request(
                "POST", create_url, headers, {"blog": {"title": "News"}}
            )
            return str(created.get("blog", {}).get("id", ""))
        except Exception:
            return ""

    def _make_request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any] | None = None,
        use_form: bool = False,
    ) -> dict[str, Any]:
        data: bytes | None = None
        if payload is not None:
            if use_form:
                data = urllib.parse.urlencode(
                    {k: v for k, v in payload.items() if v is not None}
                ).encode("utf-8")
                headers = {
                    **headers,
                    "Content-Type": "application/x-www-form-urlencoded",
                }
            else:
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
