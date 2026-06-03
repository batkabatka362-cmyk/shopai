"""Instagram Publisher Engine — W963-15.

Operator wrapper around InstagramAdapter (Graph API v21.0).
Mirrors W963-10 pinterest_publisher and W963-12 tiktok_publisher
patterns.

  shopai instagram status                                -- ready?
  shopai instagram connect --token X --account-id Y      -- save
  shopai instagram posts                                 -- list
  shopai instagram publish-post --caption C \\
       --media-url U --type IMAGE|VIDEO|REELS            -- publish

Instagram publishing is a 2-step async dance (create container
-> publish). The adapter wraps both steps so callers get a
single yes/no result + the final media id.

Why Instagram matters: completes the visual-social trifecta
(Pinterest + TikTok + Instagram). Most beauty / fashion /
lifestyle e-commerce traffic flows through some mix of these
three platforms; missing any one leaves real audience reach on
the table.
"""
from .flow import InstagramPublisherEngine

__all__ = ["InstagramPublisherEngine"]
