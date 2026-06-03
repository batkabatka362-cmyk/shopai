"""Customer Chat Engine — W963-13.

Classifies customer messages by intent + generates draft responses.
Useful for operators handling Shopify Inbox / email / contact-form
messages. The engine works offline (deterministic rules + templates)
and optionally enhances responses via an LLM adapter when one is
configured.

Why deterministic baseline:
  - Operator can preview responses without LLM keys
  - Works even when offline / LLM down
  - Tests are reproducible
  - LLM enhancement layers ON TOP -- doesn't replace the base

Intent classes (6):
  order_status     -- "Where is my order?", "tracking #"
  shipping         -- "When will it arrive?", "shipping cost"
  returns          -- "Want to return", "refund please"
  product_question -- "Does it work with...", "size guide"
  complaint        -- "Disappointed", "broken", "wrong item"
  greeting_other   -- generic fallback

CLI:
  shopai chat respond --message "Where is my order?"
                      [--order-id 1234]
                      [--customer-name "Mary"]
                      [--use-llm]
                      [--json]
"""
from .flow import CustomerChatEngine

__all__ = ["CustomerChatEngine"]
