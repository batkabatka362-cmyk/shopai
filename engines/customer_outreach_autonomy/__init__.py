"""Customer outreach autonomy domain (Wave 379+).

8th production autonomy domain. Auto-tags customers identified
as needing operator outreach via SHOPIFY_TAG_CUSTOMER.

5-piece template:
  - outreach_log     event journal
  - outreach_state   pause flag
  - outreach_health  failure-ratio analyzer + bridge
  - outreach_applier curated-taxonomy tag writer
  - outreach_status  empire-wide rollup
"""
