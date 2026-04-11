"""Mentality / values subsystem.

Wave 2 #2 in-place improvement: ShopAI's decision path already
uses weighted judgment checks (``JudgmentAdvisor._CHECK_DEFAULTS``)
and EMA-tracked action weights (``core/learning/action_weights``).
What's missing is a way to say *"this operator prioritises
reliability over speed"* and have that preference actually bend
the weighted averages.

This module adds:

* :class:`Values` — a small dataclass of named principles with
  numeric weights (``safety``, ``reliability``, ``automation``,
  ``speed``, ``long_term``, ``short_term``). Default ordering
  matches the ShopAI design tenet *"safe first, learn forever"*.
* :func:`Values.score` — weighted-sum utility for picking between
  options with mixed attributes.
* :func:`Values.check_multiplier` — maps a judgment check name
  (e.g. ``"past_failures"``, ``"cooldown"``) to a multiplier so
  :class:`core.judgment.judgment_advisor.JudgmentAdvisor` can
  re-weight its internal safety checks to match the tenant's
  principles, without any edit to the checks themselves.
* :class:`BeliefStore` — minimal beta-binomial posterior tracker
  for binary-outcome beliefs (``"did X succeed?"``). Used by
  :meth:`JudgmentAdvisor.update_belief` to accumulate evidence
  across cycles and keep the gate's confidence calibrated.

The :class:`Values` object is pure configuration — stateless and
cheap to construct. :class:`BeliefStore` is the only stateful
piece and lives in memory (persistence is out of scope for Wave 2
#2; the reflection synthesizer will snapshot beliefs to disk when
it runs in Wave 2 #5).
"""
from __future__ import annotations

from .values import (
    BeliefStore,
    Values,
    get_default_belief_store,
    reset_default_belief_store,
    set_default_belief_store,
)

__all__ = [
    "Values",
    "BeliefStore",
    "get_default_belief_store",
    "set_default_belief_store",
    "reset_default_belief_store",
]
