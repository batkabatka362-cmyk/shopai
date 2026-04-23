"""Business model + traffic channel + risk-level enums.

These three enums are the cross-cutting axes of the 4×4 matrix
in ``docs/BUSINESS_MODEL_MATRIX.md``:

    BusinessModel × Channel = 16 possible playbooks,
    each gated by a per-action RiskLevel.

Today only ``(BusinessModel.DROPSHIPPING, Channel.PAID_ADS)``
has a complete autonomous loop. The enums exist so the rest of
the codebase can REFERENCE the axes while we incrementally
fill in the other 15 cells — nothing else changes today.

Phase 1 (this commit): enums declared + wired into
``LaunchGoal`` with defaults that preserve Deguar's existing
launch path.

Phase 2 (later): ``RiskLevel`` enforcement via approval queue.
See docs/BUSINESS_MODEL_MATRIX.md §"Implementation phases".

Pure stdlib. No runtime behaviour change.
"""
from __future__ import annotations

from enum import Enum


class BusinessModel(str, Enum):
    """How the store sources what it sells.

    Value is the string handle — used for LLM prompts, log
    lines, and metafield tags. ``str, Enum`` subclass so
    ``goal.business_model == "dropshipping"`` works (backward
    compat with any existing string compares) while
    ``BusinessModel.DROPSHIPPING`` is the canonical form for
    new code.
    """

    #: Sourced from wholesale / supplier networks (CJ, AutoDS,
    #: Spocket, Alibaba). Supplier ships to buyer. ShopAI's
    #: default — Deguar's current model.
    DROPSHIPPING = "dropshipping"

    #: Owner manufactures or holds inventory. Ships from the
    #: owner's warehouse or 3PL. Requires PO + stock tracking.
    OWN_PRODUCTS = "own_products"

    #: Digital goods — ebooks, templates, courses, licenses.
    #: No physical shipping, no inventory, file/key delivery.
    DIGITAL = "digital"

    #: Promotes someone else's product; revenue = commission.
    #: Requires affiliate network adapter + click tracking.
    PARTNERSHIP = "partnership"

    @classmethod
    def from_string(cls, value: str) -> "BusinessModel":
        """Case-insensitive lookup for user-supplied strings."""
        if not value:
            return cls.DROPSHIPPING
        key = value.strip().lower().replace("-", "_")
        for m in cls:
            if m.value == key:
                return m
        raise ValueError(
            f"unknown business model: {value!r}. "
            f"Known: {[m.value for m in cls]}",
        )

    def human_label(self) -> str:
        return {
            BusinessModel.DROPSHIPPING: "Dropshipping",
            BusinessModel.OWN_PRODUCTS: "Own products",
            BusinessModel.DIGITAL: "Digital products",
            BusinessModel.PARTNERSHIP: "Partnership / affiliate",
        }[self]


class Channel(str, Enum):
    """How the store reaches buyers.

    Orthogonal to ``BusinessModel`` — any model can use any
    channel (though some pairings are more natural than
    others; see the matrix doc).
    """

    #: Meta / Google / TikTok paid traffic. Budget-controlled,
    #: instantly scalable, attribution via pixel.
    PAID_ADS = "paid_ads"

    #: Organic video / photo / blog / UGC. Free, slow, cumulative
    #: brand equity. Reels, TikTok posts, YouTube Shorts,
    #: blog articles.
    CONTENT = "content"

    #: On-page + technical SEO. Long tail: schema.org, sitemaps,
    #: domain authority, llms.txt for AI crawlers.
    SEO = "seo"

    #: Owned audience — Discord servers, Telegram groups,
    #: Facebook groups, email list. Low CAC retention path.
    COMMUNITY = "community"

    @classmethod
    def from_string(cls, value: str) -> "Channel":
        if not value:
            return cls.PAID_ADS
        key = value.strip().lower().replace("-", "_")
        for c in cls:
            if c.value == key:
                return c
        raise ValueError(
            f"unknown channel: {value!r}. "
            f"Known: {[c.value for c in cls]}",
        )

    def human_label(self) -> str:
        return {
            Channel.PAID_ADS: "Paid ads",
            Channel.CONTENT: "Organic content",
            Channel.SEO: "Search / SEO",
            Channel.COMMUNITY: "Community",
        }[self]


class RiskLevel(str, Enum):
    """Per-action risk classification for the approval gate.

    Phase 1 (this commit): enum declared, not yet enforced.

    Phase 2: ``core/system/risk_gate.py`` will route each
    action by level — LOW auto-approves, MEDIUM auto-approves
    when ``auto_approve=True``, HIGH + CRITICAL queue to
    Telegram for owner confirm. See
    ``docs/BUSINESS_MODEL_MATRIX.md`` §"Risk classification".

    The string values are intentionally stable + sorted so
    ``max(level_a, level_b)`` gives the correct "escalate to
    strictest" semantic once we define the ordering.
    """

    #: Metafield write, tag add, page update, collection
    #: membership change. Reversible in <1 min.
    LOW = "low"

    #: Price change <10%, product draft/publish, image upload,
    #: blog post publish. Reversible in <10 min.
    MEDIUM = "medium"

    #: New ad campaign, budget increase, discount code create,
    #: supplier order. Commits money. Reversible but costs.
    HIGH = "high"

    #: live_execution flip, delete action, policy rewrite,
    #: checkout config, >$100/day ad spend, new store connect.
    #: Irreversible or expensive rollback.
    CRITICAL = "critical"

    #: Numeric rank for comparison / escalation. ``max()`` of
    #: two ``RiskLevel`` ranks gives the strictest gate.
    def rank(self) -> int:
        return {
            RiskLevel.LOW: 0,
            RiskLevel.MEDIUM: 1,
            RiskLevel.HIGH: 2,
            RiskLevel.CRITICAL: 3,
        }[self]

    @classmethod
    def from_string(cls, value: str) -> "RiskLevel":
        if not value:
            return cls.MEDIUM
        key = value.strip().lower()
        for r in cls:
            if r.value == key:
                return r
        raise ValueError(
            f"unknown risk level: {value!r}. "
            f"Known: {[r.value for r in cls]}",
        )

    def requires_owner_approval(
        self, auto_approve: bool = False,
    ) -> bool:
        """Phase 1 placeholder for the Phase 2 gate. Encodes the
        policy from the matrix doc:

            LOW       → always auto
            MEDIUM    → auto if auto_approve=True, else queue
            HIGH      → always queue (owner confirm)
            CRITICAL  → always queue + double-confirm

        Callers that already route through
        ``core.autonomous.controller`` + ``auto_approve`` flag
        keep their behaviour. New code can ask this method
        whether to enqueue.
        """
        if self == RiskLevel.LOW:
            return False
        if self == RiskLevel.MEDIUM:
            return not auto_approve
        return True  # HIGH + CRITICAL always need confirm
