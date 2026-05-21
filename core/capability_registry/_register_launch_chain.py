"""First batch of capability registrations: the launch chain.

This file is the **template** for how other modules should
declare their capabilities. Each entry maps a real engine /
applier / writer to a Capability dataclass.

Why bootstrap-style file (not per-module @register decorators)
--------------------------------------------------------------
Two competing concerns:

A. Capability data should live **near the code** so it stays
   accurate when the code changes (decorator pattern).
B. The registry should be **populated unconditionally** at
   import time regardless of which modules a particular
   process actually uses (centralised bootstrap).

For the first batch we pick B -- a single
``_register_launch_chain.py`` keeps every launch-chain
registration visible side-by-side, makes audit easy, and
postpones the per-module decorator pattern until the schema
has stabilised. Future iterations can migrate to decorators
once the fields stop changing.

Adding new capabilities here is cheap and reversible. Adding
a new schema FIELD is the more expensive change -- once a
field exists in published registrations, removing it requires
touching every registration site.
"""
from __future__ import annotations

from .registry import (
    Capability,
    CapabilityKind,
    register_capability,
)


def register_all() -> None:
    """Idempotent registration of every launch-chain
    capability. Called from
    ``core.capability_registry.bootstrap.ensure_registered``.
    """

    # ── Orchestrator ──────────────────────────────────────

    register_capability(Capability(
        name="launch_store",
        kind=CapabilityKind.ORCHESTRATOR,
        description=(
            "Single-command store launch. Runs the 7-step "
            "pipeline (policies, pages, discount, "
            "collections, brand, design, products) and "
            "returns a per-step checklist plus a "
            "ready_to_launch boolean."
        ),
        when_to_use=(
            "Use when an operator says 'launch this store', "
            "'set up the store', 'make the store launchable', "
            "or any task whose outcome is a working "
            "storefront on a fresh Shopify install. Closes "
            "up to 7 of 9 launch_audit checks in one shot."
        ),
        module_path=(
            "engines.store_setup.launch_orchestrator:launch_store"
        ),
        inputs={
            "store_name": "str (required)",
            "niche": "str (general|beauty|fashion|home|tech|food)",
            "region": "str (us|eu|uk)",
            "founder_name": "str | None",
            "logo_url": "str | None (triggers Step 5)",
            "favicon_url": "str | None (triggers Step 5)",
            "seed_products": "bool (triggers Step 7)",
        },
        outputs={
            "policies": "applier result dict",
            "pages": "applier result dict",
            "discount": "applier result dict",
            "collections": "applier result dict",
            "brand": "applier result dict",
            "design": "applier result dict",
            "products": "applier result dict",
            "checklist": "list of per-step ok/applied/error",
            "ready_to_launch": "bool",
        },
        side_effects=[
            "creates Shopify policies / pages / discount / "
            "collections / theme files / brand files / "
            "starter products",
            "records SHOPAI_LAUNCH_STORE via Pattern Z "
            "(MemoryIntel + DataArch + LearningLoop)",
        ],
        audit_checks_closed=[
            "legal_policies", "standard_pages",
            "active_discounts", "curated_collections",
            "design_tokens", "brand_assets",
            "active_products",
        ],
        composes_with=["audit_store", "post_launch_enrich"],
        example_input={
            "store_name": "Acme Beauty",
            "niche": "beauty",
            "region": "us",
        },
        tags=["launch", "setup", "store-bootstrap"],
        cli_commands=["shopai launch <store_name>"],
    ))

    # ── Audit ─────────────────────────────────────────────

    register_capability(Capability(
        name="audit_store",
        kind=CapabilityKind.AUDIT,
        description=(
            "Read-only launch-readiness audit. Runs 9 cheap "
            "checks against the store and reports per-check "
            "pass/fail + fix_hint + a smart next_action "
            "recommendation."
        ),
        when_to_use=(
            "Use to verify 'is this store launchable / "
            "ready to take orders?' before claiming a "
            "launch is done. Safe on a cron -- no writes. "
            "Pairs with launch_store as the post-write "
            "verification step."
        ),
        module_path=(
            "engines.store_setup.launch_audit:audit_store"
        ),
        inputs={
            "store_id": "str | None",
            "expected_products": "int (default 1)",
            "expected_collections": "int (default 1)",
            "expected_discounts": "int (default 1)",
        },
        outputs={
            "checks": "list of {key, ok, applied, expected, "
                      "missing, fix_hint}",
            "ready_to_launch": "bool",
            "completion_pct": "int 0-100",
            "missing_summary": "str",
            "next_action": "str (highest-leverage next "
                           "command)",
        },
        side_effects=[
            "records SHOPAI_AUDIT_LAUNCH via Pattern Z",
        ],
        composes_with=["launch_store", "post_launch_enrich"],
        example_input={"store_id": "store-a"},
        tags=["audit", "launch", "verification", "read-only"],
        cli_commands=["shopai launch-audit"],
    ))

    # ── Post-launch enrichers ─────────────────────────────

    register_capability(Capability(
        name="enrich_seo",
        kind=CapabilityKind.ENRICHER,
        description=(
            "Generate SEO title + meta_description for each "
            "product. Skips products whose existing SEO meta "
            "is already populated unless overwrite=True."
        ),
        when_to_use=(
            "Use after a store has products but the SEO "
            "meta is missing or weak. Improves search "
            "visibility per product."
        ),
        module_path=(
            "engines.store_setup.seo_meta_enricher:enrich_seo"
        ),
        inputs={
            "products": "list of {id, title, product_type, "
                        "vendor, body_html}",
            "niche": "str",
            "store_name": "str",
            "overwrite_existing": "bool",
        },
        outputs={"generated": "list", "skipped": "list"},
        composes_with=["apply_seo", "audit_store"],
        tags=["post-launch", "seo", "enrichment"],
    ))

    register_capability(Capability(
        name="apply_seo",
        kind=CapabilityKind.APPLIER,
        description=(
            "Push SEO title + meta_description per product "
            "via SHOPIFY_UPDATE_PRODUCT. Pattern Z recording "
            "per product."
        ),
        when_to_use=(
            "Use after enrich_seo to write the generated "
            "metadata to Shopify."
        ),
        module_path=(
            "engines.store_setup.seo_meta_enricher:apply_seo"
        ),
        inputs={
            "products_with_seo": "list",
            "store_id": "str | None",
        },
        outputs={
            "applied_count": "int",
            "results": "list of per-product ok/error",
        },
        side_effects=[
            "writes Shopify product seo fields",
            "records per-product writeback via Pattern Z",
        ],
        scopes_used=["write_products"],
        composes_with=["enrich_seo"],
        tags=["post-launch", "seo", "writer"],
    ))

    register_capability(Capability(
        name="enrich_descriptions",
        kind=CapabilityKind.ENRICHER,
        description=(
            "Generate body_html for each product. Skips "
            "products whose existing description is at "
            "least min_existing_length characters."
        ),
        when_to_use=(
            "Use when products have thin or missing body "
            "copy. Pairs with apply_descriptions."
        ),
        module_path=(
            "engines.store_setup.product_description_enricher"
            ":enrich_products"
        ),
        inputs={
            "products": "list",
            "niche": "str",
            "min_existing_length": "int",
        },
        outputs={"generated": "list", "skipped": "list"},
        composes_with=["apply_descriptions"],
        tags=["post-launch", "content", "enrichment"],
    ))

    register_capability(Capability(
        name="apply_descriptions",
        kind=CapabilityKind.APPLIER,
        description=(
            "Push body_html per product via "
            "SHOPIFY_UPDATE_PRODUCT. Pattern Z recording "
            "per product."
        ),
        when_to_use=(
            "Use after enrich_descriptions to write the "
            "generated body_html to Shopify."
        ),
        module_path=(
            "engines.store_setup.product_description_enricher"
            ":apply_descriptions"
        ),
        inputs={
            "products_with_descriptions": "list",
            "store_id": "str | None",
        },
        outputs={
            "applied_count": "int",
            "results": "list",
        },
        side_effects=[
            "writes Shopify product body_html",
            "records via Pattern Z",
        ],
        scopes_used=["write_products"],
        composes_with=["enrich_descriptions"],
        tags=["post-launch", "content", "writer"],
    ))

    register_capability(Capability(
        name="post_launch_enrich",
        kind=CapabilityKind.ORCHESTRATOR,
        description=(
            "Companion to launch_store: walk every product "
            "and run SEO + description enrichment in one "
            "shot. Preview by default; --apply opts in."
        ),
        when_to_use=(
            "Use after launch_store when the store has "
            "products that need their SEO meta + body_html "
            "polished. Doesn't add products."
        ),
        module_path="cli:_cmd_post_launch",
        composes_with=[
            "enrich_seo", "apply_seo",
            "enrich_descriptions", "apply_descriptions",
            "audit_store",
        ],
        tags=["post-launch", "orchestrator"],
        cli_commands=["shopai post-launch"],
    ))

    # ── Step generators + appliers (launch chain interior) ─

    register_capability(Capability(
        name="generate_policies",
        kind=CapabilityKind.GENERATOR,
        description=(
            "Build the 5 standard legal policies "
            "(refund/privacy/ToS/shipping/contact) tailored "
            "to a store_name + niche + region."
        ),
        when_to_use=(
            "Use when a fresh store needs legal policies. "
            "Pairs with apply_policies."
        ),
        module_path=(
            "engines.store_setup.policy_generator:"
            "generate_policies"
        ),
        composes_with=["apply_policies"],
        tags=["launch", "policies"],
    ))

    register_capability(Capability(
        name="apply_policies",
        kind=CapabilityKind.APPLIER,
        description=(
            "Push legal policies via "
            "SHOPIFY_UPDATE_SHOP_POLICY. Pattern Z per "
            "policy."
        ),
        when_to_use="Pairs with generate_policies.",
        module_path=(
            "engines.store_setup.policy_applier:apply_policies"
        ),
        side_effects=[
            "writes Shopify shop policies",
            "records via Pattern Z",
        ],
        scopes_used=["write_legal_policies"],
        audit_checks_closed=["legal_policies"],
        composes_with=["generate_policies"],
        tags=["launch", "policies", "writer"],
    ))

    register_capability(Capability(
        name="generate_pages",
        kind=CapabilityKind.GENERATOR,
        description=(
            "Build standard storefront pages (About, "
            "Contact, FAQ, Shipping & Returns) tailored "
            "to niche + founder_name."
        ),
        when_to_use="Pairs with apply_pages.",
        module_path=(
            "engines.store_setup.page_generator:generate_pages"
        ),
        composes_with=["apply_pages"],
        tags=["launch", "pages"],
    ))

    register_capability(Capability(
        name="apply_pages",
        kind=CapabilityKind.APPLIER,
        description="Push pages via SHOPIFY_CREATE_PAGE.",
        when_to_use="Pairs with generate_pages.",
        module_path=(
            "engines.store_setup.page_applier:apply_pages"
        ),
        side_effects=[
            "creates Shopify pages",
            "records via Pattern Z",
        ],
        scopes_used=["write_content"],
        audit_checks_closed=["standard_pages"],
        composes_with=["generate_pages"],
        tags=["launch", "pages", "writer"],
    ))

    register_capability(Capability(
        name="generate_welcome_discount",
        kind=CapabilityKind.GENERATOR,
        description=(
            "Build the WELCOMEx discount code for a fresh "
            "store. Niche-aware percentage."
        ),
        when_to_use="Pairs with apply_welcome_discount.",
        module_path=(
            "engines.store_setup.welcome_discount:"
            "generate_welcome_discount"
        ),
        composes_with=["apply_welcome_discount"],
        tags=["launch", "discount"],
    ))

    register_capability(Capability(
        name="apply_welcome_discount",
        kind=CapabilityKind.APPLIER,
        description=(
            "Push the welcome discount via "
            "SHOPIFY_CREATE_DISCOUNT."
        ),
        when_to_use="Pairs with generate_welcome_discount.",
        module_path=(
            "engines.store_setup.welcome_discount:"
            "apply_welcome_discount"
        ),
        side_effects=[
            "creates a Shopify discount code",
            "records via Pattern Z",
        ],
        scopes_used=["write_discounts"],
        audit_checks_closed=["active_discounts"],
        composes_with=["generate_welcome_discount"],
        tags=["launch", "discount", "writer"],
    ))

    register_capability(Capability(
        name="generate_starter_collections",
        kind=CapabilityKind.GENERATOR,
        description=(
            "Niche-aware 4-5 starter collection specs."
        ),
        when_to_use="Pairs with apply_starter_collections.",
        module_path=(
            "engines.store_setup.collection_seeder:"
            "generate_starter_collections"
        ),
        composes_with=["apply_starter_collections"],
        tags=["launch", "collections"],
    ))

    register_capability(Capability(
        name="apply_starter_collections",
        kind=CapabilityKind.APPLIER,
        description="Push collections via "
                    "SHOPIFY_CREATE_COLLECTION.",
        when_to_use="Pairs with generate_starter_collections.",
        module_path=(
            "engines.store_setup.collection_seeder:"
            "apply_starter_collections"
        ),
        side_effects=[
            "creates Shopify collections",
            "records via Pattern Z",
        ],
        scopes_used=["write_products"],
        audit_checks_closed=["curated_collections"],
        composes_with=["generate_starter_collections"],
        tags=["launch", "collections", "writer"],
    ))

    register_capability(Capability(
        name="generate_starter_products",
        kind=CapabilityKind.SEEDER,
        description=(
            "Niche-aware 4 starter product specs (ACTIVE, "
            "tagged 'starter')."
        ),
        when_to_use=(
            "Use when a store has zero ACTIVE products and "
            "needs a placeholder catalog to pass the audit's "
            "active_products check."
        ),
        module_path=(
            "engines.store_setup.product_seeder:"
            "generate_starter_products"
        ),
        composes_with=["apply_starter_products"],
        tags=["launch", "products", "seeder"],
    ))

    register_capability(Capability(
        name="apply_starter_products",
        kind=CapabilityKind.APPLIER,
        description=(
            "Push starter products via "
            "SHOPIFY_CREATE_PRODUCT."
        ),
        when_to_use="Pairs with generate_starter_products.",
        module_path=(
            "engines.store_setup.product_seeder:"
            "apply_starter_products"
        ),
        side_effects=[
            "creates Shopify products with ACTIVE status",
            "records via Pattern Z",
        ],
        scopes_used=["write_products"],
        audit_checks_closed=["active_products"],
        composes_with=["generate_starter_products"],
        tags=["launch", "products", "writer", "seeder"],
        cli_commands=["shopai store seed-products"],
    ))

    register_capability(Capability(
        name="upload_brand_assets",
        kind=CapabilityKind.APPLIER,
        description=(
            "Upload logo + favicon (+ optional hero + "
            "og_image) via SHOPIFY_CREATE_FILES with the "
            "audit-recognisable alt-text convention."
        ),
        when_to_use=(
            "Use when an operator supplies brand asset URLs "
            "and the store should display them."
        ),
        module_path=(
            "engines.store_setup.brand_uploader:"
            "upload_brand_assets"
        ),
        side_effects=[
            "uploads Shopify files",
            "records via Pattern Z",
        ],
        scopes_used=["write_files"],
        audit_checks_closed=["brand_assets"],
        tags=["launch", "brand", "writer"],
        cli_commands=["shopai store brand-upload"],
    ))

    register_capability(Capability(
        name="apply_design",
        kind=CapabilityKind.APPLIER,
        description=(
            "Upsert shopai-design-tokens.json + the matching "
            "snippet into the MAIN theme."
        ),
        when_to_use=(
            "Use after StoreDesignEngine.run() produces a "
            "successful design envelope. Pairs with the "
            "design engine output."
        ),
        module_path=(
            "engines.store_design.design_applier:apply_design"
        ),
        side_effects=[
            "writes theme files via SHOPIFY_UPSERT_THEME_FILES",
            "records via Pattern Z",
        ],
        scopes_used=["write_themes"],
        audit_checks_closed=["design_tokens"],
        tags=["launch", "design", "writer"],
        cli_commands=["shopai store design-apply"],
    ))

    register_capability(Capability(
        name="store_design_engine",
        kind=CapabilityKind.ENGINE,
        description=(
            "Engine that produces design recommendations "
            "(layout, color, navigation, mobile) from brand "
            "+ products + analytics signal."
        ),
        when_to_use=(
            "Use when a task involves how the store LOOKS -- "
            "theme design, mobile UX, color contrast, "
            "navigation layout, brand voice consistency."
        ),
        module_path=(
            "engines.store_design.flow:StoreDesignEngine"
        ),
        composes_with=["apply_design"],
        tags=["design", "engine", "ui"],
    ))


# Module-level no-op so that simply importing this file
# doesn't auto-register. Bootstrap calls register_all()
# explicitly to keep test fixtures in control.
