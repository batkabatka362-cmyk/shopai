"""Dream replay — simulated experience for rare events.

Humans consolidate learning overnight by replaying and perturbing
the day's experience. Some AGI designs do the same: prioritised
experience replay with perturbations that broaden generalisation.

ShopAI already does deterministic consolidation (v5) — cluster,
compress, contradict, reinforce. Dream replay adds *perturbation*:
take a rare event, vary one of its features, ask the world model
to predict the counterfactual outcome, and fold the result back
as a *synthetic* training signal. This is how the brain can
generalise from a handful of rare examples.

Key choices:

  • Rarity = epistemic coverage tier 'cold' for at least one
    feature on the event.
  • Each original event spawns ``fan_out`` dreams; each dream
    perturbs exactly one feature to a plausible neighbour (pulled
    from the event's own feature vocabulary).
  • The resulting predicted outcome is stored with a
    ``synthetic=True`` flag so the regular learning loop can
    discount them by a ``synthetic_weight`` (default 0.3) when
    updating rules / rewards.

Safety: perturbations never suggest actions or write to any
external system — they only generate synthetic training rows for
the world model / reward model. No side effects on Shopify, ads,
or memory categorised as `decision`.

Pure Python. The world-model + reward-model APIs we already have
provide the rollout; this module is pure orchestration.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable


_DEFAULT_FAN_OUT = 3
_DEFAULT_SYNTHETIC_WEIGHT = 0.3


@dataclass
class DreamSample:
    source_event_id: str
    perturbed_field: str
    original_value: Any
    dream_value: Any
    predicted_outcome: float
    confidence: float
    synthetic_weight: float
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_event_id": self.source_event_id,
            "perturbed_field": self.perturbed_field,
            "original_value": self.original_value,
            "dream_value": self.dream_value,
            "predicted_outcome": round(self.predicted_outcome, 3),
            "confidence": round(self.confidence, 3),
            "synthetic_weight": round(self.synthetic_weight, 3),
            "note": self.note,
        }


@dataclass
class DreamReport:
    dreams: list[DreamSample] = field(default_factory=list)
    considered_events: int = 0
    rare_events: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "dreams": [d.as_dict() for d in self.dreams],
            "considered_events": self.considered_events,
            "rare_events": self.rare_events,
            "total_dreams": len(self.dreams),
        }


# ── Planner ─────────────────────────────────────────────────

def replay(
    events: Iterable[dict[str, Any]],
    *,
    is_rare: Callable[[dict[str, Any]], bool],
    vocab: dict[str, list[Any]],
    predictor: Callable[[dict[str, Any]], tuple[float, float]],
    fan_out: int = _DEFAULT_FAN_OUT,
    synthetic_weight: float = _DEFAULT_SYNTHETIC_WEIGHT,
    rng: random.Random | None = None,
) -> DreamReport:
    """Run one dream-replay pass.

    Args:
        events: raw experience rows; each must carry ``id`` plus
            feature fields.
        is_rare: predicate deciding whether an event is rare
            enough to warrant dreaming. Typically backed by
            epistemic.coverage_engine().
        vocab: ``{field: [possible_values]}`` dictionary so dreams
            can perturb within reachable neighbours. Values equal
            to the event's current value are skipped automatically.
        predictor: callable taking a perturbed event and returning
            ``(predicted_outcome, confidence)``. Typically wraps
            ``world_model.predict``.
        fan_out: dreams per rare event.
        synthetic_weight: how much to discount each synthetic row
            when the caller folds it back.
    """
    rng = rng or random.Random()
    report = DreamReport()
    for event in events:
        report.considered_events += 1
        if not is_rare(event):
            continue
        report.rare_events += 1
        # Collect fields we can perturb (have at least 2 vocab values,
        # one of which is the current)
        perturbable_fields = [
            f for f, vals in vocab.items()
            if f in event and any(v != event[f] for v in vals)
        ]
        if not perturbable_fields:
            continue
        for _ in range(fan_out):
            field = rng.choice(perturbable_fields)
            candidates = [
                v for v in vocab[field] if v != event[field]
            ]
            if not candidates:
                continue
            dream_value = rng.choice(candidates)
            perturbed = dict(event)
            perturbed[field] = dream_value
            outcome, conf = predictor(perturbed)
            report.dreams.append(DreamSample(
                source_event_id=str(event.get("id", "?")),
                perturbed_field=field,
                original_value=event[field],
                dream_value=dream_value,
                predicted_outcome=float(outcome),
                confidence=float(conf),
                synthetic_weight=synthetic_weight,
                note=(f"{field}: {event[field]!r} → {dream_value!r}"),
            ))
    return report


# ── Consolidation hook ─────────────────────────────────────

def fold_dreams(
    dreams: list[DreamSample],
    fold_fn: Callable[[dict[str, Any], float], None],
) -> int:
    """Apply every dream to a downstream learner. ``fold_fn`` receives
    the perturbed event dict + the weight (already scaled by
    ``synthetic_weight × confidence``). Returns the number folded."""
    count = 0
    for d in dreams:
        perturbed = {d.perturbed_field: d.dream_value,
                     "predicted_outcome": d.predicted_outcome,
                     "source_event_id": d.source_event_id}
        weight = d.synthetic_weight * d.confidence
        if weight <= 0:
            continue
        fold_fn(perturbed, weight)
        count += 1
    return count
