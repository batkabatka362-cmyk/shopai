"""AGI Arm Recommender — W963-80 (Phase 5 opener).

The bridge from Phase 4 observability to autonomy. Reads
the empire's CURRENT signal (verdict + trajectory + streak
+ anomaly + go-live state) and recommends which engines to
ARM (apply_X=True) or DISARM (apply_X=False) for the next
cycle.

Decision recipe (verdict-driven):

  earning + improving
    -> maintain current arm set
    -> ADD exploration engines (transfer_scan,
        content_publisher) -- compound the wins
  earning + flat
    -> maintain current arm set; suggest no changes
  earning + declining trend
    -> ARM retention engines (loyalty, cart_recovery,
        churn_prediction) -- preserve the base
    -> NO new spend engines
  organic_only
    -> ARM revenue-driving engines (loyalty,
        email_marketing, affiliate, ads_launcher) --
        we have revenue but AGI doesn't attribute it;
        need to establish attribution
  attributed_loss
    -> DISARM all spend engines (ads_launcher,
        pinterest_publisher, instagram_publisher,
        tiktok_publisher) -- we're bleeding
    -> ARM conservation engines (refund_applier,
        discount_cleanup, cart_recovery)
  no_data
    -> ARM kick-start engines (content_publisher,
        product_sourcer, blog_post_generator) -- get
        catalog + content moving so cycles produce signal

Override rules (HIGHER priority than verdict band):

  critical_anomaly_count > 0
    -> DISARM destructive engines this cycle (act
        conservatively while operator investigates)
  loss_streak.count >= 2 * threshold (critical)
    -> DISARM ALL spend engines (operator already
        ignoring N cycles of bleeding signal)
  no_data_streak.count >= 2 * threshold
    -> Empire is genuinely idle -- arm only kick-start
        engines

ADVISORY: this engine produces RECOMMENDATIONS, not
auto-actions. The operator runs ``shopai arm-recommend``,
sees suggestions + rationale, then applies via existing
``shopai autonomy-arm <domain>`` or skips. W963-81 will
add the env-gated auto-apply path; W963-80 is advisory
only.

Pattern J + Pattern Q.

CLI:
  shopai arm-recommend
  shopai arm-recommend --json
"""
from .flow import AgiArmRecommenderEngine

__all__ = ["AgiArmRecommenderEngine"]
