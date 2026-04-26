"""Shopify Native adapter bootstrap.

Single entry point that instantiates every Shopify native
adapter and registers it with ``AdapterRegistry``. Mirrors
``core.adapters.llm.bootstrap`` so the controller can call
both at startup with the same idempotency guarantees.

Usage::

    from core.adapters.shopify.bootstrap import register_all
    register_all()                            # use AdapterConfig env vars
    register_all(shop_url="...", access_token="...")  # explicit creds

Adapters whose credentials are unset still register with the
registry; the smart router skips them via ``is_configured()``.
This means a freshly-bootstrapped controller can list every
Shopify adapter via ``registry.list()`` even before the operator
has wired up Shopify credentials.
"""
from __future__ import annotations

from utils.logger import get_logger

from ..registry import AdapterRegistry, get_registry
from .abandoned_checkouts import ShopifyAbandonedCheckoutsAdapter
from .analytics import ShopifyAnalyticsAdapter
from .app_subscriptions import ShopifyAppSubscriptionsAdapter
from .apps import ShopifyAppsAdapter
from .articles import ShopifyArticlesAdapter
from .bulk import ShopifyBulkOperationsAdapter
from .bulk_mutations import ShopifyBulkMutationsAdapter
from .carrier_services import ShopifyCarrierServicesAdapter
from .cart_transforms import ShopifyCartTransformsAdapter
from .catalogs import ShopifyCatalogsAdapter
from .channels import ShopifyChannelsAdapter
from .collection_membership import ShopifyCollectionMembershipAdapter
from .collections import ShopifyCollectionsAdapter
from .companies import ShopifyCompaniesAdapter
from .company_contact_roles import ShopifyCompanyContactRolesAdapter
from .company_auxiliary import ShopifyCompanyAuxiliaryAdapter
from .company_contacts import ShopifyCompanyContactsAdapter
from .company_locations import ShopifyCompanyLocationsAdapter
from .customer_consent import ShopifyCustomerConsentAdapter
from .customer_merge import ShopifyCustomerMergeAdapter
from .customer_payment_methods import ShopifyCustomerPaymentMethodsAdapter
from .customer_addresses import ShopifyCustomerAddressesAdapter
from .customers import ShopifyCustomersAdapter
from .delivery_profiles import ShopifyDeliveryProfilesAdapter
from .customizations import (
    ShopifyDeliveryCustomizationsAdapter,
    ShopifyPaymentCustomizationsAdapter,
)
from .discount_activate import ShopifyDiscountActivateAdapter
from .discount_automatic import ShopifyDiscountAutomaticAdapter
from .discount_automatic_bxgy import ShopifyDiscountAutomaticBxgyAdapter
from .discount_code_bxgy import ShopifyDiscountCodeBxgyAdapter
from .discount_code_free_shipping import (
    ShopifyDiscountCodeFreeShippingAdapter,
)
from .discounts import ShopifyDiscountAdapter
from .disputes import ShopifyDisputesAdapter
from .draft_order_calculate import ShopifyDraftOrderCalculateAdapter
from .draft_order_invoice import ShopifyDraftOrderInvoiceSendAdapter
from .draft_orders import ShopifyDraftOrdersAdapter
from .files import ShopifyFilesAdapter
from .fulfillment import ShopifyFulfillmentAdapter
from .fulfillment_tracking import ShopifyFulfillmentTrackingAdapter
from .fulfillment_events import ShopifyFulfillmentEventsAdapter
from .fulfillment_hold import ShopifyFulfillmentHoldAdapter
from .fulfillment_order_ops import ShopifyFulfillmentOrderOpsAdapter
from .fulfillment_services import ShopifyFulfillmentServicesAdapter
from .generic_tags import ShopifyGenericTagsAdapter
from .gift_card_crud import ShopifyGiftCardCRUDAdapter
from .gift_cards import ShopifyGiftCardsAdapter
from .inventory import ShopifyInventoryAdapter
from .inventory_adjust import ShopifyInventoryAdjustAdapter
from .inventory_activation import ShopifyInventoryActivationAdapter
from .inventory_shipments import ShopifyInventoryShipmentsAdapter
from .inventory_transfer import ShopifyInventoryTransferAdapter
from .locations import ShopifyLocationsAdapter
from .market_web_presences import ShopifyMarketWebPresencesAdapter
from .marketing_events import ShopifyMarketingEventsAdapter
from .market_crud import ShopifyMarketCRUDAdapter
from .markets import ShopifyMarketsAdapter
from .metafield import ShopifyMetafieldAdapter
from .metafield_definition_pin import ShopifyMetafieldDefinitionPinAdapter
from .metafields_delete import ShopifyMetafieldsDeleteAdapter
from .metafield_definitions import ShopifyMetafieldDefinitionsAdapter
from .metaobject_definitions import ShopifyMetaobjectDefinitionsAdapter
from .metaobjects import ShopifyMetaobjectsAdapter
from .metaobjects_upsert import ShopifyMetaobjectsUpsertAdapter
from .order_edits import ShopifyOrderEditsAdapter
from .order_invoice import ShopifyOrderInvoiceSendAdapter
from .order_transactions import ShopifyOrderTransactionsAdapter
from .order_lifecycle import ShopifyOrderLifecycleAdapter
from .order_payment import ShopifyOrderPaymentAdapter
from .order_risk_assessment import ShopifyOrderRiskAssessmentAdapter
from .orders import ShopifyOrdersAdapter
from .pages import ShopifyPagesAdapter
from .payment_reminder import ShopifyPaymentReminderAdapter
from .payment_terms import ShopifyPaymentTermsAdapter
from .payments_payouts import ShopifyPaymentsPayoutsAdapter
from .price_list_fixed_prices import ShopifyPriceListFixedPricesAdapter
from .price_lists import ShopifyPriceListAdapter
from .product_duplicate import ShopifyProductDuplicateAdapter
from .product_media import ShopifyProductMediaAdapter
from .product_options import ShopifyProductOptionsAdapter
from .products import ShopifyProductsAdapter
from .publications import ShopifyPublicationsAdapter
from .refunds import ShopifyRefundsAdapter
from .returns import ShopifyReturnsAdapter
from .risk import ShopifyRiskAdapter
from .script_tags import ShopifyScriptTagsAdapter
from .segments import ShopifyCustomerSegmentsAdapter
from .selling_plan_groups import ShopifySellingPlanGroupsAdapter
from .shop import ShopifyShopAdapter
from .subscription_draft import ShopifySubscriptionDraftAdapter
from .subscriptions import ShopifySubscriptionContractsAdapter
from .themes import ShopifyThemesAdapter
from .translations import ShopifyTranslationsAdapter
from .validations import ShopifyValidationsAdapter
from .web_pixels import ShopifyWebPixelsAdapter
from .webhooks import ShopifyWebhooksAdapter

logger = get_logger("adapters.shopify.bootstrap")


_SHOPIFY_ADAPTER_CLASSES = (
    ShopifyRiskAdapter,
    ShopifyInventoryAdapter,
    ShopifyFulfillmentAdapter,
    ShopifyMetafieldAdapter,
    ShopifyDiscountAdapter,
    ShopifyFilesAdapter,
    ShopifyDraftOrdersAdapter,
    ShopifyMarketingEventsAdapter,
    ShopifyReturnsAdapter,
    ShopifyMetaobjectsAdapter,
    ShopifyPublicationsAdapter,
    ShopifyOrderEditsAdapter,
    ShopifyThemesAdapter,
    ShopifyAnalyticsAdapter,
    ShopifyTranslationsAdapter,
    ShopifyCustomerSegmentsAdapter,
    ShopifyRefundsAdapter,
    ShopifyPaymentCustomizationsAdapter,
    ShopifyDeliveryCustomizationsAdapter,
    ShopifyGiftCardsAdapter,
    ShopifySubscriptionContractsAdapter,
    ShopifyMarketsAdapter,
    ShopifyWebPixelsAdapter,
    ShopifyCompaniesAdapter,
    ShopifyLocationsAdapter,
    ShopifyInventoryShipmentsAdapter,
    ShopifyChannelsAdapter,
    ShopifyCartTransformsAdapter,
    ShopifyValidationsAdapter,
    ShopifyProductsAdapter,
    ShopifyOrdersAdapter,
    ShopifyCustomersAdapter,
    ShopifyWebhooksAdapter,
    ShopifyBulkOperationsAdapter,
    ShopifyShopAdapter,
    ShopifyPagesAdapter,
    ShopifyArticlesAdapter,
    ShopifyBulkMutationsAdapter,
    ShopifyDisputesAdapter,
    ShopifyDeliveryProfilesAdapter,
    ShopifyDraftOrderCalculateAdapter,
    ShopifySellingPlanGroupsAdapter,
    ShopifyCustomerPaymentMethodsAdapter,
    ShopifyAppsAdapter,
    ShopifyAbandonedCheckoutsAdapter,
    ShopifyCollectionsAdapter,
    ShopifyMetafieldDefinitionsAdapter,
    ShopifyPriceListAdapter,
    ShopifyCarrierServicesAdapter,
    ShopifyFulfillmentServicesAdapter,
    ShopifyDiscountAutomaticAdapter,
    ShopifyMetaobjectDefinitionsAdapter,
    ShopifyScriptTagsAdapter,
    ShopifyOrderTransactionsAdapter,
    ShopifyPaymentTermsAdapter,
    ShopifyMarketWebPresencesAdapter,
    ShopifyDraftOrderInvoiceSendAdapter,
    ShopifyCustomerMergeAdapter,
    ShopifyFulfillmentEventsAdapter,
    ShopifyCustomerConsentAdapter,
    ShopifyInventoryActivationAdapter,
    ShopifyDiscountCodeBxgyAdapter,
    ShopifySubscriptionDraftAdapter,
    ShopifyCatalogsAdapter,
    ShopifyFulfillmentHoldAdapter,
    ShopifyPaymentsPayoutsAdapter,
    ShopifyOrderInvoiceSendAdapter,
    ShopifyCompanyContactRolesAdapter,
    ShopifyMetaobjectsUpsertAdapter,
    ShopifyAppSubscriptionsAdapter,
    ShopifyDiscountCodeFreeShippingAdapter,
    ShopifyDiscountAutomaticBxgyAdapter,
    ShopifyCompanyLocationsAdapter,
    ShopifyMarketCRUDAdapter,
    ShopifyCustomerAddressesAdapter,
    ShopifyGiftCardCRUDAdapter,
    ShopifyCompanyContactsAdapter,
    ShopifyProductDuplicateAdapter,
    ShopifyDiscountActivateAdapter,
    ShopifyOrderLifecycleAdapter,
    ShopifyCollectionMembershipAdapter,
    ShopifyInventoryAdjustAdapter,
    ShopifyOrderRiskAssessmentAdapter,
    ShopifyFulfillmentTrackingAdapter,
    ShopifyProductMediaAdapter,
    ShopifyPriceListFixedPricesAdapter,
    ShopifyOrderPaymentAdapter,
    ShopifyMetafieldDefinitionPinAdapter,
    ShopifyCompanyAuxiliaryAdapter,
    ShopifyInventoryTransferAdapter,
    ShopifyGenericTagsAdapter,
    ShopifyProductOptionsAdapter,
    ShopifyPaymentReminderAdapter,
    ShopifyFulfillmentOrderOpsAdapter,
    ShopifyMetafieldsDeleteAdapter,
)


def register_all(
    shop_url: str | None = None,
    access_token: str | None = None,
    registry: AdapterRegistry | None = None,
) -> dict[str, bool]:
    """Instantiate every Shopify native adapter and register it.

    Args:
        shop_url: Optional shop URL to override the one from
            ``AdapterConfig``. Useful for multi-store setups
            where each store needs its own adapter instance.
        access_token: Optional access token override.
        registry: Optional explicit registry (test injection).

    Returns:
        ``{adapter_name: is_configured}`` map.
    """
    reg = registry or get_registry()
    status: dict[str, bool] = {}

    for cls in _SHOPIFY_ADAPTER_CLASSES:
        try:
            adapter = cls(shop_url=shop_url, access_token=access_token)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "failed to instantiate %s: %s", cls.__name__, exc,
            )
            continue

        try:
            reg.register(adapter, replace=True)
            status[adapter.name] = adapter.is_configured()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "failed to register %s: %s", adapter.name, exc,
            )

    configured = sum(1 for v in status.values() if v)
    logger.info(
        "Shopify native adapters registered: %d total, %d configured",
        len(status), configured,
    )
    return status
