"""AutoDSAdapter -- AutoDS dropshipping platform sourcing.

AutoDS (https://www.autods.com) is a paid dropshipping automation
platform with a developer API. Complements CJDropshipping (the
primary free-tier sourcing adapter) for operators who want
richer supplier coverage + automated order fulfilment across
AliExpress / Walmart / Costco / etc.

Auth model: a single API token in the Authorization header.
Operator generates the token from AutoDS dashboard ->
Developer Settings -> Generate API Token.

Endpoints documented at: https://devs-autods.gitbook.io/autods-api/

This adapter is a SKELETON shipped W963-102:
  * Auth + config wiring complete
  * Capability dispatch table in place
  * HTTP plumbing inherited from SourcingBaseAdapter
  * Concrete endpoint URLs + request bodies marked TODO
    until the operator's actual AutoDS docs are reviewed +
    confirmed at runtime against a live token.

Why ship the skeleton now rather than wait:
  * Registers ``autods`` in the adapter registry so
    api-status surfaces "AutoDS configured / not" once the
    token arrives.
  * Locks in the config alias name + capability set, so
    engines that want to "use AutoDS" can route via the
    abstract Capability.SOURCING_SEARCH_PRODUCTS chain
    without vendor-specific branching.
  * When the operator runs ``shopai api-status --missing-only``
    AutoDS appears as an explicit row with the env-var name
    + signup URL, not a silent gap.

To complete (after operator confirms docs / endpoints):
  * Replace _BASE_URL placeholder with the live AutoDS
    base URL (likely ``https://platform-api.autods.com`` or
    similar -- needs confirmation).
  * Fill in _do_search_products / _do_get_product /
    _do_create_order / _do_get_order_status with the
    concrete request shape + response normalisation.
  * Add live integration tests that hit the AutoDS sandbox
    if they offer one.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from ..base import AdapterResult, Capability
from ..errors import AdapterError
from ._base import SourcingBaseAdapter

logger = get_logger("adapters.sourcing.autods")


# Placeholder base URL; operator confirms via AutoDS dashboard.
# Override at instantiation if AutoDS publishes a different host.
_BASE_URL = "https://platform-api.autods.com"


class AutoDSAdapter(SourcingBaseAdapter):
    """AutoDS dropshipping platform adapter (skeleton).

    Wired into the bootstrap + api-status registry. Concrete
    endpoint paths land in a follow-up commit once the
    operator confirms AutoDS API docs against a live token.
    """

    name = "autods"
    base_url = _BASE_URL

    # Single-token auth -- AUTODS_API_TOKEN via Bearer header.
    config_alias = "autods"

    capabilities = {
        Capability.SOURCING_SEARCH_PRODUCTS,
        Capability.SOURCING_GET_PRODUCT,
        Capability.SOURCING_CREATE_ORDER,
        Capability.SOURCING_GET_ORDER_STATUS,
    }

    # Paid supplier with broader coverage than CJ -- slot
    # below CJ (the default free option) so CJ wins router
    # ties on identical capability declarations.
    priority = 75
    cost_per_call = 0.0
    requires_key = True

    # ── Capability dispatch overrides ─────────────────────────
    #
    # Each handler short-circuits with a clear "endpoint not
    # yet wired" error rather than fabricating a fake
    # response. This keeps the autonomous loop honest:
    # callers can detect "the adapter is configured but
    # not yet operational" via the standard AdapterResult
    # error path.

    def _do_search_products(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        self._validate_search_products(params)
        return self._not_yet_wired(
            capability,
            "AutoDS product search endpoint not yet wired -- "
            "see https://devs-autods.gitbook.io/autods-api/",
        )

    def _do_get_product(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        self._validate_get_product(params)
        return self._not_yet_wired(
            capability,
            "AutoDS product-detail endpoint not yet wired",
        )

    def _do_create_order(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        self._validate_create_order(params)
        return self._not_yet_wired(
            capability,
            "AutoDS order-create endpoint not yet wired",
        )

    def _do_get_order_status(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        self._validate_get_order_status(params)
        return self._not_yet_wired(
            capability,
            "AutoDS order-status endpoint not yet wired",
        )

    # ── Skeleton helpers ──────────────────────────────────────

    def _not_yet_wired(
        self, capability: Capability, detail: str,
    ) -> AdapterResult:
        """Honest 'configured but not yet operational' path.

        Returns a failure AdapterResult instead of raising so
        the router's fallback chain naturally tries the next
        sourcing adapter (typically CJDropshipping) without
        treating this as a vendor-side error.
        """
        # Touch the API key to surface AdapterNotConfigured
        # when the token is missing -- skeleton AND its
        # callers should not bypass the configured-ness gate.
        self._api_key()
        logger.info(
            "AutoDS skeleton called (%s): %s",
            capability.value, detail,
        )
        return AdapterResult.failure(
            adapter=self.name,
            capability=capability.value,
            error=AdapterError(self.name, detail),
        )
