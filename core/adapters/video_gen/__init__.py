"""Video generation / stock adapters.

Every adapter wraps one video source behind the uniform
``BaseAdapter`` interface so the ad_creative_generator engine
can compose videos from any mix of stock libraries and AI
generators without vendor-specific code.

Capabilities exposed:

  * :attr:`Capability.VIDEO_STOCK_SEARCH` — keyword → stock clips
    (Pexels, Pixabay)
  * :attr:`Capability.VIDEO_GENERATE`     — prompt → AI video job
    (Higgsfield, Replicate)
  * :attr:`Capability.VIDEO_GET_STATUS`   — poll async AI job
    (Higgsfield, Replicate)

Sources (priority-ordered within each mode):

  * Stock:  ``pexels`` (90), ``pixabay`` (75)
  * AI:     ``higgsfield`` (85), ``replicate`` (70)

Every adapter returns the same :func:`VideoGenBaseAdapter.
_normalise_clip` shape so downstream engines are vendor-agnostic.

Bootstrap::

    from core.adapters.video_gen.bootstrap import register_all
    register_all()
"""
from ._base import VideoGenBaseAdapter

__all__ = ["VideoGenBaseAdapter"]
