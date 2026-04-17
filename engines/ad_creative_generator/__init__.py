"""Ad Creative Generator engine.

Takes a ranked winner (output of :mod:`engines.winning_products`)
plus the product's commerce data and produces a complete
creative pack — video plan, voiceover script, five angle-specific
copy variants, thumbnails spec, and cost estimate — that the
product_launch orchestrator can push to Meta / TikTok ads.

See :mod:`engines.ad_creative_generator.flow` for the public
``run`` entry point.
"""
from .flow import ENGINE_NAME, AdCreativeGeneratorEngine, run

__all__ = ["ENGINE_NAME", "AdCreativeGeneratorEngine", "run"]
