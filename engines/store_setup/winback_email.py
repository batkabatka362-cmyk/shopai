"""Niche-aware win-back email content for lapsed customers.

Customer lifecycle emails shipped so far:
  * Welcome (#383)
  * Abandoned cart (#383)
  * Review request (#394)

This module adds the fourth: the **win-back email** sent
to customers who haven't ordered in 180+ days. These are
the customers in the ``Lapsed (180d)`` segment from
``customer_segments.py`` (#389) -- the cohort that's
slipped beyond the at-risk window and needs a steeper
incentive to come back.

Industry math:
  * Win-back open rates: 8-15% (lower than active
    audience).
  * When they DO convert, AOV is often 1.3-1.5x typical
    -- customers who come back tend to buy more.
  * The right code is steeper than the welcome offer
    (gone 6+ months -> bigger nudge needed).

Three sequence variants:
  * **soft** -- "We miss you", no discount, brand-voice
    only. Fires at 180d.
  * **incentive** -- "Here's $X off", real money,
    fires at 210d when soft didn't convert.
  * **last_chance** -- "This is the last email", reduces
    list-clutter + drives urgency. Fires at 240d when
    incentive didn't convert. List cleanup: customers
    who don't open this get auto-unsubscribed
    (Klaviyo-side rule).

Pairs with ``coupon_playbook.seasonal`` percentage --
the win-back incentive code uses a 20-30% off code,
matching seasonal-clearance percentages by niche.
"""
from __future__ import annotations

import html
import logging
from typing import Any

from engines._writeback_recorder import record_writeback

logger = logging.getLogger(__name__)


# Niche-specific subject lines for each sequence step.
# Format: (soft, incentive, last_chance)
_NICHE_SUBJECTS: dict[str, tuple[str, str, str]] = {
    "beauty": (
        "{{first_name}}, we miss you",
        "{{first_name}}, here's 20% off your comeback",
        "Last call: 25% off + we're cleaning the list",
    ),
    "fashion": (
        "Where've you been, {{first_name}}?",
        "{{first_name}}, 25% off welcomes you back",
        "Final email: 30% off, then we lose touch",
    ),
    "tech": (
        "We've missed you, {{first_name}}",
        "{{first_name}}, here's 15% to come back",
        "Last call -- 20% off then we stop emailing",
    ),
    "home": (
        "{{first_name}}, we miss you",
        "20% off to refresh your space",
        "Last email from us -- 25% off + goodbye",
    ),
    "food": (
        "{{first_name}}, the pantry misses you",
        "15% off your comeback order",
        "Final: 20% off, then we go quiet",
    ),
    "pets": (
        "{{first_name}}, how's your pet?",
        "20% off welcomes you (+ your pet) back",
        "Last call: 25% off, then we lose touch",
    ),
    "fitness": (
        "Still training, {{first_name}}?",
        "15% off welcomes you back to training",
        "Final email: 20% off, then we stop",
    ),
    "jewelry": (
        "{{first_name}}, we miss you",
        "10% off your next piece",
        "Last call: 15% off + we say goodbye",
    ),
    "outdoor": (
        "Hit the trail lately, {{first_name}}?",
        "20% off welcomes you back to the trail",
        "Last call: 25% off, then we go quiet",
    ),
    "baby": (
        "{{first_name}}, how's your little one?",
        "20% off welcomes you back",
        "Last email: 25% off + we move on",
    ),
    "general": (
        "{{first_name}}, we miss you",
        "20% off your comeback order",
        "Last email: 25% off + we go quiet",
    ),
}


# Niche-specific body openings -- the personalised "we
# miss you" line each variant builds from.
_NICHE_OPENINGS: dict[str, str] = {
    "beauty": (
        "It's been a while since you last shopped with "
        "{{store.name}}. The routine waits for you "
        "whenever you're ready."
    ),
    "fashion": (
        "It's been a few seasons since your last "
        "{{store.name}} order. Whatever's in your "
        "wardrobe rotation -- we'd love to be part of "
        "it again."
    ),
    "tech": (
        "It's been a while since your last "
        "{{store.name}} order. Whatever you've upgraded "
        "since, we'd love to help you find the next "
        "thing."
    ),
    "home": (
        "It's been a while since your last "
        "{{store.name}} order. Spaces change. We'd "
        "love to be part of yours again."
    ),
    "food": (
        "It's been a while since your last "
        "{{store.name}} order. We've got new arrivals "
        "in every category -- worth a look."
    ),
    "pets": (
        "It's been a while since your last "
        "{{store.name}} order. We hope your pet is "
        "doing well -- here's a nudge if you're "
        "running low on anything."
    ),
    "fitness": (
        "It's been a while since your last "
        "{{store.name}} order. Whether you're still "
        "training hard or coming back from a break, "
        "we're here for the gear you need."
    ),
    "jewelry": (
        "It's been a while since your last "
        "{{store.name}} piece. We've added new arrivals "
        "across every category -- worth a look."
    ),
    "outdoor": (
        "It's been a while since your last "
        "{{store.name}} order. Whatever the next trip "
        "looks like, we'd love to gear you up for it."
    ),
    "baby": (
        "It's been a while since your last "
        "{{store.name}} order. Your little one has "
        "grown -- we'd love to help you find what fits "
        "this stage."
    ),
    "general": (
        "It's been a while since your last "
        "{{store.name}} order. We'd love to have you "
        "back when you're ready."
    ),
}


_WINBACK_PAGE_TITLE: str = "Win-Back Email Sequence"
_WINBACK_PAGE_HANDLE: str = "winback-email"


def generate_winback_sequence(
    *,
    store_name: str,
    niche: str = "general",
    incentive_code: str | None = None,
    incentive_pct: int | None = None,
    last_chance_code: str | None = None,
    last_chance_pct: int | None = None,
    days_after_lapse_soft: int = 0,
    days_after_lapse_incentive: int = 30,
    days_after_lapse_last_chance: int = 60,
) -> dict[str, Any]:
    """Build the 3-step win-back sequence.

    All days_after_lapse_* are relative to entering the
    Lapsed (180d) segment. So soft=0 fires immediately
    on entering, incentive=+30 fires at 210d total,
    last_chance=+60 fires at 240d total.

    Args:
        store_name: Display name. Empty -> empty dict.
        niche: Lowercase niche key. Unknown -> general.
        incentive_code: Discount code for the incentive
            step. Pair with welcome / coupon playbook for
            consistent code naming.
        incentive_pct: Percent off for the incentive
            step. Used in subject template substitution.
        last_chance_code: Discount code for the
            last-chance step (typically steeper).
        last_chance_pct: Percent off for last chance.
        days_after_lapse_soft: Days after entering the
            Lapsed segment to send the soft email.
        days_after_lapse_incentive: For the incentive
            email.
        days_after_lapse_last_chance: For the
            last-chance email.

    Returns:
        ``{store_name, niche, templates: {soft,
        incentive, last_chance}}``.
    """
    name = (store_name or "").strip()
    if not name:
        return {}

    niche_n = (niche or "general").strip().lower() or "general"
    subjects = _NICHE_SUBJECTS.get(
        niche_n, _NICHE_SUBJECTS["general"],
    )
    opening = _NICHE_OPENINGS.get(
        niche_n, _NICHE_OPENINGS["general"],
    )

    inc_code = (incentive_code or "").strip().upper() or None
    inc_pct = (
        int(incentive_pct)
        if incentive_pct is not None
        and int(incentive_pct) > 0
        else None
    )
    lc_code = (last_chance_code or "").strip().upper() or None
    lc_pct = (
        int(last_chance_pct)
        if last_chance_pct is not None
        and int(last_chance_pct) > 0
        else None
    )

    soft = _build_soft(
        name=name,
        subject=subjects[0],
        opening=opening,
        days_after_lapse=int(days_after_lapse_soft),
    )
    incentive = _build_incentive(
        name=name,
        subject_template=subjects[1],
        opening=opening,
        code=inc_code,
        pct=inc_pct,
        days_after_lapse=int(days_after_lapse_incentive),
    )
    last_chance = _build_last_chance(
        name=name,
        subject_template=subjects[2],
        opening=opening,
        code=lc_code,
        pct=lc_pct,
        days_after_lapse=int(
            days_after_lapse_last_chance,
        ),
    )

    return {
        "store_name": name,
        "niche": niche_n,
        "templates": {
            "soft": soft,
            "incentive": incentive,
            "last_chance": last_chance,
        },
    }


def _build_soft(
    *,
    name: str,
    subject: str,
    opening: str,
    days_after_lapse: int,
) -> dict[str, Any]:
    body_text = (
        f"Hi {{{{first_name}}}},\n\n"
        f"{opening}\n\n"
        "If you've got a minute, we'd love to know what "
        "would bring you back -- new arrivals, free "
        "shipping, a different category. Reply to this "
        "email; a real person reads every message.\n\n"
        f"-- The {name} team"
    )
    body_html = (
        f"<p>Hi {{{{first_name}}}},</p>"
        f"<p>{opening}</p>"
        "<p>If you've got a minute, we'd love to know "
        "what would bring you back -- new arrivals, "
        "free shipping, a different category. Reply to "
        "this email; a real person reads every "
        "message.</p>"
        "<p><a href=\"{{shop.url}}/collections/all\" "
        "class=\"btn\">Browse the store</a></p>"
        f"<p>-- The {name} team</p>"
    )
    return {
        "subject": subject,
        "preheader": (
            "No pressure, no discount -- we just want to "
            "know what'd bring you back."
        ),
        "body_text": body_text,
        "body_html": body_html,
        "trigger": (
            f"{days_after_lapse} days after entering "
            "Lapsed (180d) segment"
        ),
    }


def _build_incentive(
    *,
    name: str,
    subject_template: str,
    opening: str,
    code: str | None,
    pct: int | None,
    days_after_lapse: int,
) -> dict[str, Any]:
    if code and pct:
        subject = _subject_with_pct(
            subject_template, pct,
        )
        reward_text = (
            f"\n\nHere's a nudge: code {code} takes "
            f"{pct}% off your next order. Valid for 14 "
            "days from this email."
        )
        reward_html = (
            f"<p><strong>Use code <code>{code}</code></strong> "
            f"for {pct}% off your next order. Valid for "
            "14 days.</p>"
        )
        preheader = (
            f"Code {code} -- {pct}% off, 14 days only."
        )
    else:
        subject = subject_template
        reward_text = (
            "\n\nWe've put a special offer in your account "
            "-- log in to see it."
        )
        reward_html = (
            "<p><strong>A special offer is waiting in "
            "your account.</strong> Log in to claim.</p>"
        )
        preheader = (
            "A welcome-back offer is waiting in your "
            "account."
        )

    body_text = (
        f"Hi {{{{first_name}}}},\n\n"
        f"{opening}"
        f"{reward_text}\n\n"
        f"-- The {name} team"
    )
    body_html = (
        f"<p>Hi {{{{first_name}}}},</p>"
        f"<p>{opening}</p>"
        f"{reward_html}"
        "<p><a href=\"{{shop.url}}/collections/all\" "
        "class=\"btn\">Shop the store</a></p>"
        f"<p>-- The {name} team</p>"
    )
    return {
        "subject": subject,
        "preheader": preheader,
        "body_text": body_text,
        "body_html": body_html,
        "trigger": (
            f"{days_after_lapse} days after entering "
            "Lapsed (180d) segment"
        ),
        "incentive_code": code,
        "incentive_pct": pct,
    }


def _build_last_chance(
    *,
    name: str,
    subject_template: str,
    opening: str,
    code: str | None,
    pct: int | None,
    days_after_lapse: int,
) -> dict[str, Any]:
    if code and pct:
        subject = _subject_with_pct(
            subject_template, pct,
        )
        reward_text = (
            f"\n\nFinal offer: code {code} takes "
            f"{pct}% off any order. Valid for 7 days. "
            "Don't open this one and we'll auto-"
            "unsubscribe -- no hard feelings."
        )
        reward_html = (
            f"<p><strong>Final offer: code <code>{code}"
            f"</code></strong> takes {pct}% off any "
            "order. Valid for 7 days.</p>"
            "<p><em>This is the last email we'll send "
            "if you don't engage. No hard feelings.</em></p>"
        )
        preheader = (
            f"Code {code} -- {pct}% off, then we go "
            "quiet."
        )
    else:
        subject = subject_template
        reward_text = (
            "\n\nThis is the last email we'll send if "
            "you don't engage. No hard feelings."
        )
        reward_html = (
            "<p><em>This is the last email we'll send "
            "if you don't engage. No hard feelings.</em></p>"
        )
        preheader = (
            "Final email -- then we go quiet."
        )

    body_text = (
        f"Hi {{{{first_name}}}},\n\n"
        f"{opening}"
        f"{reward_text}\n\n"
        f"-- The {name} team"
    )
    body_html = (
        f"<p>Hi {{{{first_name}}}},</p>"
        f"<p>{opening}</p>"
        f"{reward_html}"
        "<p><a href=\"{{shop.url}}/collections/all\" "
        "class=\"btn\">Shop one more time</a></p>"
        f"<p>-- The {name} team</p>"
    )
    return {
        "subject": subject,
        "preheader": preheader,
        "body_text": body_text,
        "body_html": body_html,
        "trigger": (
            f"{days_after_lapse} days after entering "
            "Lapsed (180d) segment"
        ),
        "incentive_code": code,
        "incentive_pct": pct,
    }


def _subject_with_pct(template: str, pct: int) -> str:
    """Replace the default percent in a subject template
    with the actual pct, handling the common patterns:
    `20% off`, `25% off`, `30% off`, `15% off`, `10% off`.
    """
    for default in ("30% off", "25% off", "20% off",
                    "15% off", "10% off"):
        if default in template:
            return template.replace(
                default, f"{pct}% off",
            )
    return template


def render_winback_html(
    spec: dict[str, Any],
) -> str:
    if not isinstance(spec, dict) or not spec.get(
        "templates",
    ):
        return ""

    name = html.escape(spec.get("store_name", "") or "")
    templates = spec.get("templates") or {}

    sections: list[str] = []
    for key in ("soft", "incentive", "last_chance"):
        tmpl = templates.get(key)
        if not isinstance(tmpl, dict):
            continue
        section_label = key.replace(
            "_", " ",
        ).title()
        trigger = html.escape(
            tmpl.get("trigger", "") or "",
        )
        sections.append(
            "<section class=\"winback-template\">"
            f"<h2>{html.escape(section_label)}</h2>"
            "<dl>"
            "<dt>Subject</dt>"
            f"<dd>{html.escape(tmpl.get('subject', ''))}</dd>"
            "<dt>Preheader</dt>"
            f"<dd>{html.escape(tmpl.get('preheader', ''))}</dd>"
            "<dt>Trigger</dt>"
            f"<dd>{trigger}</dd>"
            "<dt>Plain text</dt>"
            f"<dd><pre>{html.escape(tmpl.get('body_text', ''))}"
            "</pre></dd>"
            "<dt>HTML</dt>"
            f"<dd><pre>{html.escape(tmpl.get('body_html', ''))}"
            "</pre></dd>"
            "</dl>"
            "</section>"
        )

    return (
        "<section class=\"winback-emails\">"
        f"<h1>{name} -- Win-Back Email Sequence</h1>"
        "<p>3-step sequence for lapsed customers. Wire "
        "into Klaviyo / Shopify Email triggered by the "
        "<code>Lapsed (180d)</code> customer segment "
        "from <code>customer_segments</code>.</p>"
        + "".join(sections) +
        "</section>"
    )


def apply_winback(
    spec: dict[str, Any],
    *,
    store_id: str | None = None,
) -> dict[str, Any]:
    """Persist as Shopify page ``winback-email``."""
    if not isinstance(spec, dict) or not spec.get(
        "templates",
    ):
        return {
            "applied": False,
            "handle": _WINBACK_PAGE_HANDLE,
            "error": "no_winback_spec",
        }

    body_html = render_winback_html(spec)
    if not body_html:
        _record(
            success=False, store_id=store_id,
            error="empty_render", spec=spec,
        )
        return {
            "applied": False,
            "handle": _WINBACK_PAGE_HANDLE,
            "error": "empty_render",
        }

    router = _get_router()
    capability = _get_capability()
    if router is None or capability is None:
        _record(
            success=False, store_id=store_id,
            error="router_unavailable", spec=spec,
        )
        return {
            "applied": False,
            "handle": _WINBACK_PAGE_HANDLE,
            "error": "router_unavailable",
        }

    params = {
        "title": _WINBACK_PAGE_TITLE,
        "handle": _WINBACK_PAGE_HANDLE,
        "body_html": body_html,
        "published": True,
    }
    try:
        result = router.execute(capability, params)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "winback_email router.execute raised: %s",
            exc,
        )
        _record(
            success=False, store_id=store_id,
            error=str(exc), spec=spec,
        )
        return {
            "applied": False,
            "handle": _WINBACK_PAGE_HANDLE,
            "error": f"adapter_raise: {exc}",
        }

    ok = bool(getattr(result, "ok", False))
    error = getattr(result, "error", None)
    _record(
        success=ok, store_id=store_id,
        error=None if ok else str(error or "rejected"),
        spec=spec,
    )
    if ok:
        return {
            "applied": True,
            "handle": _WINBACK_PAGE_HANDLE,
            "error": None,
        }
    return {
        "applied": False,
        "handle": _WINBACK_PAGE_HANDLE,
        "error": str(error or "rejected"),
    }


# ── Helpers ───────────────────────────────────────────────────


def _record(
    *,
    success: bool,
    store_id: str | None,
    error: str | None,
    spec: dict[str, Any],
) -> None:
    templates = spec.get("templates") or {}
    params: dict[str, Any] = {
        "handle": _WINBACK_PAGE_HANDLE,
        "template_keys": sorted(templates.keys()),
    }
    if store_id:
        params["store_id"] = str(store_id)
    try:
        record_writeback(
            engine="store_setup",
            action_type="apply_winback_email",
            capability="SHOPIFY_CREATE_PAGE",
            params=params,
            success=bool(success),
            error=error,
            metrics={
                "handle": _WINBACK_PAGE_HANDLE,
                "template_count": len(templates),
                "niche": spec.get("niche", ""),
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "winback_email record_writeback raised: %s",
            exc,
        )


def _get_router() -> Any | None:
    try:
        from core.adapters import get_router as _get
        return _get()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "winback_email router import failed: %s",
            exc,
        )
        return None


def _get_capability() -> Any | None:
    try:
        from core.adapters.base import Capability
        return Capability.SHOPIFY_CREATE_PAGE
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "winback_email capability resolve failed: "
            "%s", exc,
        )
        return None
