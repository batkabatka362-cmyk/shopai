"""Core engines — long-lived domain logic built by ShopAI.

Per owner's architectural frame (CORE vs COMMODITY vs
DIFFERENTIATION): engines are our own brain/logic modules that
orchestrate commodity adapters (LLMs, email vendors, supplier
APIs, Shopify) into revenue-producing workflows.

Current engines:

  * ``email_campaigns`` — automated lifecycle emails (welcome,
    abandoned cart, post-purchase, win-back). Wires the
    Brevo / Resend adapters into scheduled flows; the
    scheduling + rendering logic is ours.

Older engines live in the top-level ``engines/`` tree and will
migrate here as they're touched. This package is the target
home for new work.
"""
