"""ShopifyMarketingEventsAdapter — record external campaigns + engagements.

ShopAI's "ads spy → launch → ROAS guardrails" pipeline launches paid
campaigns on third-party platforms (Meta, TikTok, Google) and needs to
mirror those campaigns into the merchant's Shopify Marketing dashboard
so:

  * The merchant sees every active campaign without leaving Shopify admin.
  * Daily metrics (impressions, clicks, spend, sales, conversions) flow
    into Shopify's reporting so the ROAS guardrail can read them back
    and decide pause / scale / rotate creative.
  * UTM parameters attached to a campaign let Shopify attribute the
    sales it tracks against the campaign that drove them.

Shopify exposes this via the *external marketing activity* surface —
the same API Facebook's official Shopify channel uses to push its
campaigns into the dashboard. ShopAI is the same kind of caller:
"I'm an external system reporting campaigns I launched somewhere else".

Capabilities:

  * ``SHOPIFY_CREATE_MARKETING_ACTIVITY`` — register a campaign via
    ``marketingActivityCreateExternal``.
  * ``SHOPIFY_UPDATE_MARKETING_ACTIVITY`` — change status / budget /
    schedule via ``marketingActivityUpdateExternal``.
  * ``SHOPIFY_ADD_MARKETING_ENGAGEMENT`` — push a daily metrics row
    via ``marketingEngagementCreate``.
  * ``SHOPIFY_LIST_MARKETING_ACTIVITIES`` — page through activities.

Friendly call shape so engines don't need to know about
``MarketingActivityCreateExternalInput`` or that the ``adSpend`` field
nests under ``MoneyInput`` etc.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_CREATE_ACTIVITY_MUTATION = """
mutation marketingActivityCreateExternal($input: MarketingActivityCreateExternalInput!) {
  marketingActivityCreateExternal(input: $input) {
    marketingActivity {
      id
      title
      status
      marketingChannelType
      sourceAndMedium
      adSpend {
        amount
        currencyCode
      }
      utmParameters {
        source
        medium
        campaign
        content
        term
      }
    }
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


_UPDATE_ACTIVITY_MUTATION = """
mutation marketingActivityUpdateExternal(
  $marketingActivityId: ID,
  $remoteId: String,
  $input: MarketingActivityUpdateExternalInput!
) {
  marketingActivityUpdateExternal(
    marketingActivityId: $marketingActivityId,
    remoteId: $remoteId,
    input: $input
  ) {
    marketingActivity {
      id
      title
      status
      adSpend {
        amount
        currencyCode
      }
    }
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


_ADD_ENGAGEMENT_MUTATION = """
mutation marketingEngagementCreate(
  $marketingActivityId: ID,
  $remoteId: String,
  $marketingEngagement: MarketingEngagementInput!
) {
  marketingEngagementCreate(
    marketingActivityId: $marketingActivityId,
    remoteId: $remoteId,
    marketingEngagement: $marketingEngagement
  ) {
    marketingEngagement {
      occurredOn
      impressionsCount
      viewsCount
      clicksCount
      sharesCount
      commentsCount
      favoritesCount
      uniqueViewsCount
      uniqueClicksCount
      sessionsCount
      isCumulative
      adSpend { amount currencyCode }
      sales { amount currencyCode }
    }
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


_LIST_ACTIVITIES_QUERY = """
query marketingActivities($first: Int!, $after: String, $sortKey: MarketingActivitySortKeys) {
  marketingActivities(first: $first, after: $after, sortKey: $sortKey) {
    pageInfo {
      hasNextPage
      endCursor
    }
    edges {
      node {
        id
        title
        status
        marketingChannelType
        sourceAndMedium
        adSpend {
          amount
          currencyCode
        }
        utmParameters {
          source
          medium
          campaign
          content
          term
        }
        createdAt
        updatedAt
      }
    }
  }
}
""".strip()


_DEFAULT_LIST_LIMIT = 50
_MAX_LIST_LIMIT = 250


# Friendly aliases for the MarketingChannel enum. The Shopify-correct
# values are uppercase enum names; engines may pass lowercase / vendor
# names ("facebook", "tiktok", "google") and we map them.
_CHANNEL_ALIASES = {
    "search": "SEARCH",
    "display": "DISPLAY",
    "social": "SOCIAL",
    "email": "EMAIL",
    "referral": "REFERRAL",
    "facebook": "SOCIAL",
    "instagram": "SOCIAL",
    "tiktok": "SOCIAL",
    "twitter": "SOCIAL",
    "x": "SOCIAL",
    "google": "SEARCH",
    "google_ads": "SEARCH",
    "youtube": "DISPLAY",
}

# MarketingTactic enum values Shopify accepts (required at create time).
# Friendly aliases let engines pass natural names; defaults to AD because
# 95% of ShopAI's launches are paid ads on Meta/TikTok/Google.
_MARKETING_TACTICS = {
    "ad": "AD",
    "ads": "AD",
    "paid": "AD",
    "abandoned_cart": "ABANDONED_CART",
    "cart_recovery": "ABANDONED_CART",
    "affiliate": "AFFILIATE",
    "direct_mail": "DIRECT_MAIL",
    "display": "DISPLAY",
    "link": "LINK",
    "loyalty": "LOYALTY",
    "message": "MESSAGE",
    "newsletter": "NEWSLETTER",
    "notification": "NOTIFICATION",
    "post": "POST",
    "social_post": "POST",
    "retargeting": "RETARGETING",
    "search": "SEARCH",
    "seo": "SEO",
    "storefront_app": "STOREFRONT_APP",
    "transactional": "TRANSACTIONAL",
}

_VALID_TACTICS = set(_MARKETING_TACTICS.values())


# Activity statuses Shopify accepts. We accept lowercase too.
_ACTIVITY_STATUSES = {
    "active": "ACTIVE",
    "paused": "PAUSED",
    "deleted": "DELETED",
    "deleted_externally": "DELETED_EXTERNALLY",
    "disconnected": "DISCONNECTED",
    "scheduled": "SCHEDULED",
    "draft": "INACTIVE",
    "inactive": "INACTIVE",
    "pending": "PENDING",
    "failed": "FAILED",
    "undefined": "UNDEFINED",
}


class ShopifyMarketingEventsAdapter(ShopifyBaseAdapter):
    name = "shopify_marketing_events"
    capabilities = {
        Capability.SHOPIFY_CREATE_MARKETING_ACTIVITY,
        Capability.SHOPIFY_UPDATE_MARKETING_ACTIVITY,
        Capability.SHOPIFY_ADD_MARKETING_ENGAGEMENT,
        Capability.SHOPIFY_LIST_MARKETING_ACTIVITIES,
    }
    required_scopes = frozenset({
        "read_marketing_events", "write_marketing_events",
    })

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_CREATE_MARKETING_ACTIVITY:
            return self._create_activity(params)
        if capability == Capability.SHOPIFY_UPDATE_MARKETING_ACTIVITY:
            return self._update_activity(params)
        if capability == Capability.SHOPIFY_ADD_MARKETING_ENGAGEMENT:
            return self._add_engagement(params)
        if capability == Capability.SHOPIFY_LIST_MARKETING_ACTIVITIES:
            return self._list_activities(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Create activity ────────────────────────────────────────────

    def _create_activity(self, params: dict[str, Any]) -> Any:
        activity_input = self._build_create_input(params)
        data = self._gql(
            _CREATE_ACTIVITY_MUTATION,
            {"input": activity_input},
        )
        self._check_user_errors(data, "marketingActivityCreateExternal")
        payload = data.get("marketingActivityCreateExternal") or {}
        return self._success(
            Capability.SHOPIFY_CREATE_MARKETING_ACTIVITY,
            data={
                "activity": self._normalise_activity(
                    payload.get("marketingActivity") or {}
                ),
            },
        )

    @staticmethod
    def _build_create_input(params: dict[str, Any]) -> dict[str, Any]:
        """Convert ShopAI's friendly call shape into a
        ``MarketingActivityCreateExternalInput``.

        Friendly form::

            {
              "title": "Summer Sale FB",
              "channel": "facebook",            # alias resolved
              "status": "active",               # alias resolved
              "remote_id": "fb-camp-123",       # campaign ID on Meta
              "remote_url": "https://...",      # dashboard link
              "ad_spend": {"amount": 250, "currency": "USD"},
              "utm": {                          # at least one UTM is required
                "campaign": "summer25",
                "source": "facebook",
                "medium": "cpc",
              },
              "starts_at": "2026-06-01T00:00:00Z",  # optional
              "ends_at":   "2026-08-31T23:59:59Z",  # optional
              "budget": {"total": 5000, "type": "DAILY"},  # optional
            }
        """
        title = params.get("title")
        if not isinstance(title, str) or not title.strip():
            raise AdapterValidationError(
                "shopify_marketing_events",
                "'title' is required (non-empty string)",
            )

        channel = params.get("channel") or params.get("marketing_channel_type")
        if not isinstance(channel, str) or not channel.strip():
            raise AdapterValidationError(
                "shopify_marketing_events",
                "'channel' is required (e.g. 'social', 'search', 'facebook')",
            )
        channel_resolved = _CHANNEL_ALIASES.get(
            channel.lower(), channel.upper(),
        )
        if channel_resolved not in (
            "SEARCH", "DISPLAY", "SOCIAL", "EMAIL", "REFERRAL",
        ):
            raise AdapterValidationError(
                "shopify_marketing_events",
                f"'channel' must resolve to SEARCH/DISPLAY/SOCIAL/"
                f"EMAIL/REFERRAL, got {channel!r}",
            )

        # MarketingTactic — Shopify requires a non-null tactic at create
        # time. AD is the right default because the vast majority of
        # ShopAI launches are paid ads (Meta/TikTok/Google). Engines
        # creating organic content / cart recovery / etc. can override.
        tactic_raw = params.get("tactic", "ad")
        if not isinstance(tactic_raw, str):
            raise AdapterValidationError(
                "shopify_marketing_events",
                "'tactic' must be a string",
            )
        tactic_resolved = _MARKETING_TACTICS.get(
            tactic_raw.lower(), tactic_raw.upper(),
        )
        if tactic_resolved not in _VALID_TACTICS:
            raise AdapterValidationError(
                "shopify_marketing_events",
                f"'tactic' must be one of {sorted(_VALID_TACTICS)}, "
                f"got {tactic_raw!r}",
            )

        out: dict[str, Any] = {
            "title": title.strip(),
            "marketingChannelType": channel_resolved,
            "tactic": tactic_resolved,
        }

        # Status (defaults to ACTIVE — most common case for "I just
        # launched a campaign and want to track it").
        status = params.get("status", "active")
        if not isinstance(status, str):
            raise AdapterValidationError(
                "shopify_marketing_events",
                "'status' must be a string",
            )
        status_resolved = _ACTIVITY_STATUSES.get(
            status.lower(), status.upper(),
        )
        out["status"] = status_resolved

        # UTMs — Shopify requires at least source + medium + campaign on
        # creation so the platform can attribute sales back to the
        # activity. Spec wants them in a nested dict.
        utm = params.get("utm")
        if utm is not None:
            if not isinstance(utm, dict):
                raise AdapterValidationError(
                    "shopify_marketing_events",
                    "'utm' must be a dict with source/medium/campaign",
                )
            utm_out: dict[str, str] = {}
            for k in ("campaign", "source", "medium", "content", "term"):
                v = utm.get(k)
                if v is not None:
                    if not isinstance(v, str):
                        raise AdapterValidationError(
                            "shopify_marketing_events",
                            f"'utm.{k}' must be a string",
                        )
                    if v.strip():
                        utm_out[k] = v.strip()
            # campaign + source + medium are functionally required for
            # Shopify to attribute. Reject up-front.
            for required in ("campaign", "source", "medium"):
                if required not in utm_out:
                    raise AdapterValidationError(
                        "shopify_marketing_events",
                        f"'utm.{required}' is required",
                    )
            out["utm"] = utm_out

        # Remote identifiers — the campaign's id and dashboard URL on
        # the third-party platform. ``remote_url`` is required by
        # Shopify (caught live during smoke test); it's also the
        # mechanism the merchant uses to click through from the
        # Shopify dashboard back to the source platform. ``remote_id``
        # is optional but strongly recommended so engagements can be
        # back-filled by remote_id later.
        remote_id = params.get("remote_id") or params.get("remoteId")
        if remote_id is not None:
            if not isinstance(remote_id, str):
                raise AdapterValidationError(
                    "shopify_marketing_events",
                    "'remote_id' must be a string",
                )
            out["remoteId"] = remote_id
        remote_url = params.get("remote_url") or params.get("remoteUrl")
        if not isinstance(remote_url, str) or not remote_url.strip():
            raise AdapterValidationError(
                "shopify_marketing_events",
                "'remote_url' is required (link to the campaign on its "
                "source platform — Shopify rejects activities without it)",
            )
        out["remoteUrl"] = remote_url
        remote_preview = (
            params.get("remote_preview_image_url")
            or params.get("remotePreviewImageUrl")
        )
        if remote_preview is not None:
            if not isinstance(remote_preview, str):
                raise AdapterValidationError(
                    "shopify_marketing_events",
                    "'remote_preview_image_url' must be a string",
                )
            out["remotePreviewImageUrl"] = remote_preview

        # Ad spend — Shopify wants MoneyInput (amount: Decimal,
        # currencyCode: CurrencyCode). Accept friendly form.
        ad_spend = params.get("ad_spend") or params.get("adSpend")
        if ad_spend is not None:
            out["adSpend"] = _money_input(ad_spend, where="ad_spend")

        starts_at = params.get("starts_at") or params.get("scheduledToEndAt")
        if starts_at is not None:
            if not isinstance(starts_at, str):
                raise AdapterValidationError(
                    "shopify_marketing_events",
                    "'starts_at' must be ISO-8601 string",
                )
            out["scheduledToEndAt"] = starts_at  # Shopify field is overloaded
        ends_at = params.get("ends_at") or params.get("scheduledToEndAt")
        if ends_at is not None and "scheduledToEndAt" not in out:
            if not isinstance(ends_at, str):
                raise AdapterValidationError(
                    "shopify_marketing_events",
                    "'ends_at' must be ISO-8601 string",
                )
            out["scheduledToEndAt"] = ends_at

        # Budget — Shopify rejects external activities with a null
        # budget (caught live during smoke test: "Budget can't be
        # blank, Budget type can't be blank"). The friendliest path is
        # to default budget from ad_spend when only one is provided
        # (engines that already know the spend rarely care about a
        # separate "planned budget" field). If neither is provided,
        # require an explicit budget — better to fail fast at the
        # adapter than pay the userErrors round-trip.
        budget = params.get("budget")
        if budget is None and ad_spend is not None:
            # Default from ad_spend as LIFETIME budget.
            budget = {"total": ad_spend, "type": "LIFETIME"}
        if budget is None:
            raise AdapterValidationError(
                "shopify_marketing_events",
                "'budget' is required (Shopify rejects external "
                "activities with a null budget). Pass either "
                "'budget' explicitly or 'ad_spend' to default from.",
            )
        if not isinstance(budget, dict):
            raise AdapterValidationError(
                "shopify_marketing_events",
                "'budget' must be a dict {total, type}",
            )
        total = budget.get("total")
        if total is None:
            raise AdapterValidationError(
                "shopify_marketing_events",
                "'budget.total' is required",
            )
        btype = budget.get("type", "LIFETIME")
        if not isinstance(btype, str) or btype.upper() not in (
            "DAILY", "LIFETIME",
        ):
            raise AdapterValidationError(
                "shopify_marketing_events",
                "'budget.type' must be DAILY or LIFETIME",
            )
        out["budget"] = {
            "total": _money_input(total, where="budget.total"),
            "budgetType": btype.upper(),
        }

        return out

    # ── Update activity ────────────────────────────────────────────

    def _update_activity(self, params: dict[str, Any]) -> Any:
        # The activity identifier (``marketingActivityId`` or
        # ``remoteId``) lives at the GraphQL field level, NOT inside
        # ``MarketingActivityUpdateExternalInput`` — caught live as
        # "Field is not defined on MarketingActivityUpdateExternalInput"
        # for both ``id`` and ``marketingActivityId`` attempts. The
        # input dict only carries the fields to update.
        activity_id = params.get("id") or params.get("activity_id")
        remote_id = params.get("remote_id") or params.get("remoteId")
        if not (activity_id or remote_id):
            raise AdapterValidationError(
                "shopify_marketing_events",
                "update needs 'id' (preferred) or 'remote_id'",
            )

        update_input: dict[str, Any] = {}
        if "title" in params:
            if not isinstance(params["title"], str):
                raise AdapterValidationError(
                    "shopify_marketing_events",
                    "'title' must be a string",
                )
            update_input["title"] = params["title"]
        if "status" in params:
            status = params["status"]
            if not isinstance(status, str):
                raise AdapterValidationError(
                    "shopify_marketing_events",
                    "'status' must be a string",
                )
            update_input["status"] = _ACTIVITY_STATUSES.get(
                status.lower(), status.upper(),
            )
        if "ad_spend" in params or "adSpend" in params:
            update_input["adSpend"] = _money_input(
                params.get("ad_spend") or params.get("adSpend"),
                where="ad_spend",
            )

        if not update_input:
            raise AdapterValidationError(
                "shopify_marketing_events",
                "update needs at least one field besides the identifier "
                "(title / status / ad_spend)",
            )

        variables: dict[str, Any] = {"input": update_input}
        if activity_id:
            if not isinstance(activity_id, str):
                raise AdapterValidationError(
                    "shopify_marketing_events",
                    "'id' must be a Shopify GID string",
                )
            variables["marketingActivityId"] = activity_id.strip()
        if remote_id:
            if not isinstance(remote_id, str):
                raise AdapterValidationError(
                    "shopify_marketing_events",
                    "'remote_id' must be a string",
                )
            variables["remoteId"] = remote_id.strip()

        data = self._gql(_UPDATE_ACTIVITY_MUTATION, variables)
        self._check_user_errors(data, "marketingActivityUpdateExternal")
        payload = data.get("marketingActivityUpdateExternal") or {}
        return self._success(
            Capability.SHOPIFY_UPDATE_MARKETING_ACTIVITY,
            data={
                "activity": self._normalise_activity(
                    payload.get("marketingActivity") or {}
                ),
            },
        )

    # ── Add engagement (daily metrics row) ─────────────────────────

    def _add_engagement(self, params: dict[str, Any]) -> Any:
        activity_id = params.get("activity_id") or params.get("marketingActivityId")
        remote_id = params.get("remote_id") or params.get("remoteId")
        # Schema currently only accepts marketingActivityId OR remoteId
        # — no channel-type fallback. Reject early so callers don't pay
        # the GraphQL round-trip.
        if not activity_id and not remote_id:
            raise AdapterValidationError(
                "shopify_marketing_events",
                "engagement needs 'activity_id' (preferred) "
                "or 'remote_id'",
            )

        engagement_input = self._build_engagement_input(params)
        variables: dict[str, Any] = {"marketingEngagement": engagement_input}
        if activity_id:
            if not isinstance(activity_id, str):
                raise AdapterValidationError(
                    "shopify_marketing_events",
                    "'activity_id' must be a string",
                )
            variables["marketingActivityId"] = activity_id
        if remote_id:
            if not isinstance(remote_id, str):
                raise AdapterValidationError(
                    "shopify_marketing_events",
                    "'remote_id' must be a string",
                )
            variables["remoteId"] = remote_id

        data = self._gql(_ADD_ENGAGEMENT_MUTATION, variables)
        self._check_user_errors(data, "marketingEngagementCreate")
        payload = data.get("marketingEngagementCreate") or {}
        return self._success(
            Capability.SHOPIFY_ADD_MARKETING_ENGAGEMENT,
            data={"engagement": self._normalise_engagement(
                payload.get("marketingEngagement") or {}
            )},
        )

    @staticmethod
    def _build_engagement_input(params: dict[str, Any]) -> dict[str, Any]:
        """Convert friendly engagement metrics to ``MarketingEngagementInput``.

        Friendly form::

            {
              "occurred_on": "2026-04-25",       # required, YYYY-MM-DD
              "impressions": 12345,
              "views": 1000,
              "clicks": 230,
              "shares": 5,
              "comments": 3,
              "favorites": 12,
              "unique_views": 800,
              "unique_clicks": 200,
              "sessions": 95,
              "conversions": 8,
              "spend": {"amount": 25.50, "currency": "USD"},
              "sales": {"amount": 200.00, "currency": "USD"},
              "is_cumulative": False,            # default False (per-day delta)
            }
        """
        occurred_on = params.get("occurred_on") or params.get("occurredOn")
        if not isinstance(occurred_on, str) or not occurred_on.strip():
            raise AdapterValidationError(
                "shopify_marketing_events",
                "'occurred_on' is required (YYYY-MM-DD string)",
            )

        # utcOffset is required on MarketingEngagementInput (caught
        # live during smoke test). ShopAI's metrics are emitted in UTC
        # by default, so "+00:00" is the right zero-config value;
        # callers operating on local-time data can override.
        utc_offset = params.get("utc_offset") or params.get("utcOffset") or "+00:00"
        if not isinstance(utc_offset, str):
            raise AdapterValidationError(
                "shopify_marketing_events",
                "'utc_offset' must be a string like '+00:00' or '-05:00'",
            )

        out: dict[str, Any] = {
            "occurredOn": occurred_on.strip(),
            "utcOffset": utc_offset,
            "isCumulative": bool(params.get("is_cumulative", False)),
        }

        # Note: conversionsCount is NOT on MarketingEngagement in the
        # current schema (caught live as 'undefinedField'). Conversions
        # are tracked through the Shopify analytics pipeline via
        # session attribution rather than reported here, so we drop
        # the field rather than ship a request that will be rejected.
        int_fields = {
            "impressions": "impressionsCount",
            "views": "viewsCount",
            "clicks": "clicksCount",
            "shares": "sharesCount",
            "comments": "commentsCount",
            "favorites": "favoritesCount",
            "unique_views": "uniqueViewsCount",
            "unique_clicks": "uniqueClicksCount",
            "sessions": "sessionsCount",
        }
        for friendly, shopify in int_fields.items():
            if friendly in params:
                v = params[friendly]
                try:
                    n = int(v)
                except (TypeError, ValueError) as exc:
                    raise AdapterValidationError(
                        "shopify_marketing_events",
                        f"'{friendly}' must be int, got {type(v).__name__}",
                    ) from exc
                if n < 0:
                    raise AdapterValidationError(
                        "shopify_marketing_events",
                        f"'{friendly}' must be >= 0, got {n}",
                    )
                out[shopify] = n

        spend = params.get("spend") or params.get("ad_spend") or params.get("adSpend")
        if spend is not None:
            out["adSpend"] = _money_input(spend, where="spend")
        sales = params.get("sales")
        if sales is not None:
            out["sales"] = _money_input(sales, where="sales")

        # Engagement input requires AT LEAST one metric beyond
        # occurredOn — otherwise Shopify rejects with a
        # "no measurable engagement" userError. Fail fast.
        metric_keys = set(int_fields.values()) | {"adSpend", "sales"}
        if not (set(out.keys()) & metric_keys):
            raise AdapterValidationError(
                "shopify_marketing_events",
                "engagement needs at least one metric "
                "(impressions / clicks / spend / sales / etc.)",
            )

        return out

    # ── List ───────────────────────────────────────────────────────

    def _list_activities(self, params: dict[str, Any]) -> Any:
        limit = params.get("limit", _DEFAULT_LIST_LIMIT)
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = _DEFAULT_LIST_LIMIT
        limit = max(1, min(limit, _MAX_LIST_LIMIT))

        cursor = params.get("cursor")
        if cursor is not None and not isinstance(cursor, str):
            raise AdapterValidationError(
                "shopify_marketing_events",
                "'cursor' must be a string or None",
            )
        sort_key = params.get("sort_key") or params.get("sortKey")
        if sort_key is not None and not isinstance(sort_key, str):
            raise AdapterValidationError(
                "shopify_marketing_events",
                "'sort_key' must be a string or None",
            )
        if isinstance(sort_key, str):
            sort_key = sort_key.upper()

        data = self._gql(
            _LIST_ACTIVITIES_QUERY,
            {"first": limit, "after": cursor, "sortKey": sort_key},
        )
        envelope = data.get("marketingActivities") or {}
        page_info = envelope.get("pageInfo") or {}
        edges = envelope.get("edges") or []
        activities = [
            self._normalise_activity(edge.get("node") or {})
            for edge in edges if isinstance(edge, dict)
        ]
        return self._success(
            Capability.SHOPIFY_LIST_MARKETING_ACTIVITIES,
            data={
                "activities": activities,
                "count": len(activities),
                "has_next_page": bool(page_info.get("hasNextPage", False)),
                "end_cursor": page_info.get("endCursor", "") or "",
            },
        )

    # ── Helpers ────────────────────────────────────────────────────

    @staticmethod
    def _normalise_activity(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        ad_spend = node.get("adSpend") or {}
        utm_raw = node.get("utmParameters") or {}
        try:
            spend_amount = float(ad_spend.get("amount", 0) or 0)
        except (TypeError, ValueError):
            spend_amount = 0.0
        return {
            "id": node.get("id", "") or "",
            "title": node.get("title", "") or "",
            "status": node.get("status", "") or "",
            "channel": node.get("marketingChannelType", "") or "",
            "source_and_medium": node.get("sourceAndMedium", "") or "",
            "ad_spend": spend_amount,
            "currency": ad_spend.get("currencyCode", "") or "",
            "utm": {
                "source": utm_raw.get("source", "") or "",
                "medium": utm_raw.get("medium", "") or "",
                "campaign": utm_raw.get("campaign", "") or "",
                "content": utm_raw.get("content", "") or "",
                "term": utm_raw.get("term", "") or "",
            } if utm_raw else {},
            "created_at": node.get("createdAt", "") or "",
            "updated_at": node.get("updatedAt", "") or "",
        }

    @staticmethod
    def _normalise_engagement(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        ad_spend = node.get("adSpend") or {}
        sales = node.get("sales") or {}
        try:
            spend_amount = float(ad_spend.get("amount", 0) or 0)
        except (TypeError, ValueError):
            spend_amount = 0.0
        try:
            sales_amount = float(sales.get("amount", 0) or 0)
        except (TypeError, ValueError):
            sales_amount = 0.0
        return {
            "occurred_on": node.get("occurredOn", "") or "",
            "impressions": int(node.get("impressionsCount", 0) or 0),
            "views": int(node.get("viewsCount", 0) or 0),
            "clicks": int(node.get("clicksCount", 0) or 0),
            "shares": int(node.get("sharesCount", 0) or 0),
            "comments": int(node.get("commentsCount", 0) or 0),
            "favorites": int(node.get("favoritesCount", 0) or 0),
            "unique_views": int(node.get("uniqueViewsCount", 0) or 0),
            "unique_clicks": int(node.get("uniqueClicksCount", 0) or 0),
            "sessions": int(node.get("sessionsCount", 0) or 0),
            "is_cumulative": bool(node.get("isCumulative", False)),
            "spend": spend_amount,
            "spend_currency": ad_spend.get("currencyCode", "") or "",
            "sales": sales_amount,
            "sales_currency": sales.get("currencyCode", "") or "",
        }


def _money_input(raw: Any, *, where: str) -> dict[str, Any]:
    """Normalise a ShopAI-friendly money dict into Shopify ``MoneyInput``.

    Accepts::

        {"amount": 25.50, "currency": "USD"}      # snake_case
        {"amount": "25.50", "currencyCode": "USD"}  # camelCase / string
        25.50                                      # bare number (defaults USD)

    Raises ``AdapterValidationError`` on malformed input.
    """
    if isinstance(raw, (int, float)):
        return {"amount": f"{float(raw):.2f}", "currencyCode": "USD"}
    if not isinstance(raw, dict):
        raise AdapterValidationError(
            "shopify_marketing_events",
            f"{where!r} must be a dict {{amount, currency}} or a bare number",
        )
    amount = raw.get("amount")
    if amount is None:
        raise AdapterValidationError(
            "shopify_marketing_events",
            f"{where!r} missing 'amount'",
        )
    try:
        amount_f = float(amount)
    except (TypeError, ValueError) as exc:
        raise AdapterValidationError(
            "shopify_marketing_events",
            f"{where!r} 'amount' must be numeric, got {type(amount).__name__}",
        ) from exc
    if amount_f < 0:
        raise AdapterValidationError(
            "shopify_marketing_events",
            f"{where!r} 'amount' must be >= 0, got {amount_f}",
        )
    currency = raw.get("currency") or raw.get("currencyCode") or "USD"
    if not isinstance(currency, str):
        raise AdapterValidationError(
            "shopify_marketing_events",
            f"{where!r} 'currency' must be a string",
        )
    return {"amount": f"{amount_f:.2f}", "currencyCode": currency.upper()}
