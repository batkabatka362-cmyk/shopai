"""Social page-growth adapters.

Covers the *organic* side of social — posting to a brand's
own Instagram / Facebook / TikTok page on a schedule. The
paid side (campaigns, boosts) stays in ``core/adapters/ads``;
social here is about owned reach: UGC reposts, daily product
shots, blog-article teasers that drive traffic without ad
spend.

Capabilities (shared across platforms):
  * SOCIAL_PUBLISH_POST   — publish immediately
  * SOCIAL_SCHEDULE_POST  — queue for a future time
  * SOCIAL_GET_INSIGHTS   — reach, impressions, likes,
                            comments, shares per post
  * SOCIAL_LIST_POSTS     — paginated recent posts
  * SOCIAL_DELETE_POST    — remove a post

Concrete adapters:
  * InstagramAdapter  — IG Graph API via connected FB page
  * FacebookPageAdapter — FB Pages API
  * (TikTok organic posting lives in the same TikTok Ads
    adapter's business API under v1.3/content/video/publish/;
    adding it later keeps the surface symmetric)
"""
from core.adapters.social.instagram import InstagramAdapter
from core.adapters.social.facebook_page import FacebookPageAdapter

__all__ = ["InstagramAdapter", "FacebookPageAdapter"]
