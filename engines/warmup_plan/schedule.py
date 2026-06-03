"""30-day warmup-plan schedule generator.

The schedule is anchored to fixed milestones (launch, first
ad pulse, first review ask, first earnings audit) with niche-
specific tuning on top. Beauty + fashion stores ramp faster
on social; tech + home stores need deeper SEO so blog/content
gets earlier weight.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class WarmupDay:
    day: int
    phase: str
    intent: str
    actions: list[str] = field(default_factory=list)
    measurement: str = ""
    pivot_signal: str = ""


# ── Phase definitions ───────────────────────────────────


_PHASES = {
    "foundation": "Days 1-3 — products, content, policies live",
    "ignition":   "Days 4-10 — paid + organic traffic flowing",
    "feedback":   "Days 11-20 — convert traffic, gather reviews",
    "compound":   "Days 21-30 — measure + reinvest winners",
}


def _phase_for_day(day: int) -> str:
    if day <= 3:
        return "foundation"
    if day <= 10:
        return "ignition"
    if day <= 20:
        return "feedback"
    return "compound"


# ── Niche tuning ────────────────────────────────────────

# Niches that earn faster on visual social go heavier on
# pinterest / tiktok / instagram in the ignition phase.
_SOCIAL_HEAVY = {"beauty", "fashion", "home", "food"}
_SEO_HEAVY = {"tech", "home"}


def _social_actions_for_niche(niche: str | None) -> list[str]:
    if niche and niche.lower() in _SOCIAL_HEAVY:
        return [
            "shopai pinterest publish-pin --image-url U "
            "--title T --board-id B",
            "shopai instagram publish-post --caption C "
            "--media-url U",
            "shopai tiktok publish-post --video-url V "
            "--caption C",
        ]
    return [
        "shopai pinterest publish-pin --image-url U "
        "--title T --board-id B",
    ]


def _seo_weight(niche: str | None) -> int:
    """Returns how many blog posts to queue in foundation."""
    if niche and niche.lower() in _SEO_HEAVY:
        return 5
    return 3


# ── Day generator ───────────────────────────────────────


def _foundation_day(
    day: int, niche: str | None,
) -> WarmupDay:
    if day == 1:
        return WarmupDay(
            day=1, phase=_phase_for_day(1),
            intent=(
                "Products + policies live. Launch the store."
            ),
            actions=[
                f"shopai earn-bootstrap --niche {niche or 'general'} "
                "--count 20 --yes",
                "shopai approvals approve-all "
                "--engine product_sourcer --execute",
                "shopai store configure main",
                "shopai launch \"Store Name\" "
                f"--niche {niche or 'general'} --include-legal-notice",
            ],
            measurement=(
                "shopai launch-audit -- expect >= 9/11 gates pass"
            ),
            pivot_signal=(
                "If launch-audit < 6/11, fix gaps before day 2."
            ),
        )
    if day == 2:
        return WarmupDay(
            day=2, phase=_phase_for_day(2),
            intent=(
                f"Seed {_seo_weight(niche)} SEO blog drafts for "
                "long-tail traffic in 30+ days."
            ),
            actions=[
                f"shopai blog-candidates --niche "
                f"{niche or 'general'} --apply --blog-id "
                "gid://shopify/Blog/X",
                "shopai approvals approve-all "
                "--engine content_publisher --execute",
            ],
            measurement=(
                "shopai approvals pending --engine "
                "content_publisher -- expect 0 (auto-approved)"
            ),
            pivot_signal=(
                "If approvals stall, set "
                "SHOPAI_APPROVAL_AUTO_APPROVE=1."
            ),
        )
    return WarmupDay(
        day=3, phase=_phase_for_day(3),
        intent=(
            "Channel wiring — email + ads + social credentials."
        ),
        actions=[
            "shopai email connect brevo --api-key K",
            "shopai email send-test --to operator@example.com",
            "shopai ads connect meta --token X --account-id Y",
            "shopai pinterest connect --token T "
            "--ad-account-id A",
        ],
        measurement=(
            "shopai email status && shopai ads status && "
            "shopai pinterest status -- all 3 [OK ]"
        ),
        pivot_signal=(
            "If 2+ channels fail to wire, defer launch by 24h."
        ),
    )


def _ignition_day(
    day: int, niche: str | None,
) -> WarmupDay:
    if day == 4:
        return WarmupDay(
            day=4, phase=_phase_for_day(4),
            intent="First paid pulse — $10/day cap.",
            actions=[
                "shopai ads launch --platform meta "
                "--budget-daily 10",
            ],
            measurement=(
                "shopai marketing-status -- verdict=healthy"
            ),
            pivot_signal=(
                "Burn > $5 with 0 clicks by EOD -> "
                "shopai marketing-pause."
            ),
        )
    if day == 5:
        return WarmupDay(
            day=5, phase=_phase_for_day(5),
            intent="First social pulse.",
            actions=_social_actions_for_niche(niche),
            measurement=(
                "shopai instagram posts -- verify live"
            ),
            pivot_signal=(
                "0 organic reach after 48h -> reduce post "
                "cadence + invest in pinterest."
            ),
        )
    if day == 6:
        return WarmupDay(
            day=6, phase=_phase_for_day(6),
            intent="Affiliate program live.",
            actions=[
                "shopai affiliate generate-link "
                "--partner-email seed@example.com",
            ],
            measurement="shopai affiliate status",
            pivot_signal=(
                "Skip if no partner shortlist by day 6."
            ),
        )
    if day == 7:
        return WarmupDay(
            day=7, phase=_phase_for_day(7),
            intent=(
                "Week-1 diagnostic — earnings check + "
                "first cycle run."
            ),
            actions=[
                "shopai earnings --days 7",
                "shopai cycle run --yes",
                "shopai cycle status",
            ],
            measurement=(
                "shopai earnings -- expect attributable "
                "ad-spend even if revenue==$0"
            ),
            pivot_signal=(
                "If 0 sessions all week, raise ad budget "
                "or pivot product selection."
            ),
        )
    if day in (8, 9, 10):
        return WarmupDay(
            day=day, phase=_phase_for_day(day),
            intent=(
                "Compound traffic — daily social + 1 blog "
                "per day."
            ),
            actions=_social_actions_for_niche(niche) + [
                "shopai blog-candidates --niche "
                f"{niche or 'general'} --apply",
            ],
            measurement="shopai earnings --days 3",
            pivot_signal=(
                "Daily revenue still $0 by day 10 -> review "
                "store conversion (cro-variants)."
            ),
        )
    raise ValueError(f"ignition day out of range: {day}")


def _feedback_day(
    day: int, niche: str | None,
) -> WarmupDay:
    if day == 11:
        return WarmupDay(
            day=11, phase=_phase_for_day(11),
            intent=(
                "First review-request batch — deliveries "
                "from week 1 are landing now."
            ),
            actions=[
                f"shopai reviews preview --niche "
                f"{niche or 'general'} --limit 5",
                "shopai reviews send-batch --yes "
                f"--niche {niche or 'general'} --limit 5",
            ],
            measurement="shopai reviews status",
            pivot_signal=(
                "Skip if no orders to ask yet — wait until "
                "shopai reviews preview returns eligible > 0."
            ),
        )
    if day == 12:
        return WarmupDay(
            day=12, phase=_phase_for_day(12),
            intent="Cart-recovery loop on.",
            actions=[
                "shopai approvals approve-all "
                "--engine cart_recovery --execute",
            ],
            measurement="shopai engine pulse cart_recovery",
            pivot_signal=(
                "If 0 abandoned carts by day 14, sessions "
                "aren't reaching checkout."
            ),
        )
    if day == 13:
        return WarmupDay(
            day=13, phase=_phase_for_day(13),
            intent="CRO variants — test on best-seller.",
            actions=[
                f"shopai cro variants --niche "
                f"{niche or 'general'} --product-id PID"
            ],
            measurement="shopai cro variants status",
            pivot_signal=(
                "Need >= 100 product-page sessions before "
                "running variants; revisit at day 17."
            ),
        )
    if day == 14:
        return WarmupDay(
            day=14, phase=_phase_for_day(14),
            intent=(
                "Two-week diagnostic + transfer-scan for "
                "cross-store winners (if fleet)."
            ),
            actions=[
                "shopai earnings --days 14",
                "shopai transfer scan",
            ],
            measurement=(
                "shopai empire --summarize -- verdict=earning"
            ),
            pivot_signal=(
                "Earnings $0 at day 14 -> cycle run --yes "
                "then pivot niche or unit price."
            ),
        )
    if day == 15:
        return WarmupDay(
            day=15, phase=_phase_for_day(15),
            intent="Chat AI on for customer messages.",
            actions=[
                "shopai chat respond --message-file inbox.txt",
            ],
            measurement=(
                "shopai engine pulse customer_chat"
            ),
            pivot_signal=(
                "Skip if no customer messages received."
            ),
        )
    if day == 16:
        return WarmupDay(
            day=16, phase=_phase_for_day(16),
            intent=(
                "Email marketing pulse — first newsletter."
            ),
            actions=[
                "shopai approvals approve-all "
                "--engine email_marketing --execute",
            ],
            measurement=(
                "shopai engine pulse email_marketing"
            ),
            pivot_signal=(
                "If no email list by day 16, push capture "
                "popup on the storefront."
            ),
        )
    if day in (17, 18, 19, 20):
        return WarmupDay(
            day=day, phase=_phase_for_day(day),
            intent=(
                "Daily review batch + traffic compound."
            ),
            actions=[
                f"shopai reviews send-batch --yes "
                f"--niche {niche or 'general'}",
            ] + _social_actions_for_niche(niche),
            measurement="shopai earnings --days 3",
            pivot_signal=(
                "Conversion rate < 1% by day 20 -> "
                "store_design review."
            ),
        )
    raise ValueError(f"feedback day out of range: {day}")


def _compound_day(
    day: int, niche: str | None,
) -> WarmupDay:
    if day == 21:
        return WarmupDay(
            day=21, phase=_phase_for_day(21),
            intent=(
                "Three-week earnings audit + ROAS by "
                "channel."
            ),
            actions=[
                "shopai earnings --days 21",
                "shopai roas",
            ],
            measurement="shopai engine ranking",
            pivot_signal=(
                "Channel ROAS < 1.0 -> shopai ads launch "
                "with negative budget delta."
            ),
        )
    if day in (22, 23, 24, 25):
        return WarmupDay(
            day=day, phase=_phase_for_day(day),
            intent=(
                "Reinvest winners — bump ad spend on "
                "best-ROAS channel; pause worst."
            ),
            actions=[
                "shopai roas",
                "shopai ads launch --platform meta "
                "--budget-daily 25",
            ],
            measurement="shopai marketing-status",
            pivot_signal=(
                "Per-day net negative for 3 consecutive "
                "days -> pause all paid + lean on social."
            ),
        )
    if day in (26, 27, 28):
        return WarmupDay(
            day=day, phase=_phase_for_day(day),
            intent="Loyalty + repeat-buyer activation.",
            actions=[
                "shopai approvals approve-all "
                "--engine loyalty --execute",
            ],
            measurement="shopai engine pulse loyalty",
            pivot_signal=(
                "Skip if < 10 customers — too thin for "
                "loyalty signal."
            ),
        )
    if day == 29:
        return WarmupDay(
            day=29, phase=_phase_for_day(29),
            intent=(
                "Niche-pivot check — is the product/niche "
                "fit working?"
            ),
            actions=[
                "shopai engine alerts",
                "shopai autonomy-status",
            ],
            measurement=(
                "shopai empire --summarize -- verdict"
            ),
            pivot_signal=(
                "Earnings still < $500 on 30-day = pivot "
                "candidate."
            ),
        )
    return WarmupDay(
        day=30, phase=_phase_for_day(30),
        intent=(
            "Month-1 retrospective + month-2 plan."
        ),
        actions=[
            "shopai earnings --days 30",
            "shopai engine ranking",
            "shopai transfer outcomes",
            "shopai cycle schedule",
        ],
        measurement=(
            "shopai empire -- review verdict + alerts"
        ),
        pivot_signal=(
            "If month-1 net negative, keep social + email "
            "running but pause paid ads for month-2."
        ),
    )


def generate_plan(
    niche: str | None = None,
) -> list[WarmupDay]:
    """Build the 30-day plan as a list of WarmupDay objects."""
    plan: list[WarmupDay] = []
    for day in range(1, 31):
        phase = _phase_for_day(day)
        if phase == "foundation":
            plan.append(_foundation_day(day, niche))
        elif phase == "ignition":
            plan.append(_ignition_day(day, niche))
        elif phase == "feedback":
            plan.append(_feedback_day(day, niche))
        else:
            plan.append(_compound_day(day, niche))
    return plan


def get_day(
    day: int, niche: str | None = None,
) -> WarmupDay | None:
    """Return the WarmupDay for a single day. Returns None for
    out-of-range values."""
    if day < 1 or day > 30:
        return None
    phase = _phase_for_day(day)
    if phase == "foundation":
        return _foundation_day(day, niche)
    if phase == "ignition":
        return _ignition_day(day, niche)
    if phase == "feedback":
        return _feedback_day(day, niche)
    return _compound_day(day, niche)


def phase_summary() -> dict[str, str]:
    """Return the 4 phases with their summary text."""
    return dict(_PHASES)
