"""Order followup autonomy domain (Wave 174-180).

6th autonomy domain. Post-order autonomy: tag orders with
follow-up state (e.g. shopai-followup-pending-review,
shopai-followup-thank-you-sent) so operator can filter
admin natively + downstream automations consume these tags.

Mirrors discount_cleanup_autonomy / inventory_autonomy
structure. Uses core/automation/* template.
"""
