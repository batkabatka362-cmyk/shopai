"""Goal-Driven Launch Pipeline.

Owner provides a winning-product candidate (Alibaba URL, spy-tool URL,
or supplier id). The pipeline executes the 12 steps that turn a hint
into a live, tracked Shopify listing with a running Meta Ads campaign:

    source → supplier → media → content → shopify_create →
    creative → ads_launch → tracking → monitor

Each step is idempotent and isolated — a failure in one step records
its own outcome event but does not corrupt earlier-step state. The
pipeline returns a ``LaunchResult`` with per-step status so the owner
can re-run from a specific checkpoint.

Usage:
    from workflows.launch import LaunchPipeline
    result = LaunchPipeline().run(LaunchGoal(
        alibaba_url="https://www.alibaba.com/...",
        target_price=29.99,
        ad_budget_day=20.0,
        niche="pets",
    ))
"""
from __future__ import annotations

from .context import LaunchGoal, LaunchContext, LaunchResult
from .pipeline import LaunchPipeline

__all__ = ["LaunchGoal", "LaunchContext", "LaunchResult", "LaunchPipeline"]
