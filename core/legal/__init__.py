"""L7 legal compliance — page templates + region logic.

See docs/AGI_STACK.md layer L7 (governance) and Sprint 3 S3-2.
"""
from core.legal.compliance import (
    LegalPage,
    LegalPageSet,
    render_legal_pages,
    REGION_US,
    REGION_EU,
    REGION_UK,
)

__all__ = [
    "LegalPage",
    "LegalPageSet",
    "render_legal_pages",
    "REGION_US",
    "REGION_EU",
    "REGION_UK",
]
