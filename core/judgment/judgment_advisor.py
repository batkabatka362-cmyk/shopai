"""JudgmentAdvisor — "Is NOW the right time to execute this decision?"

Pre-execution gate that sits between DECIDE and EXECUTE.
Checks 6 factors before allowing a decision to proceed:

1. Magnitude check: big change + low confidence → escalate
2. Competitor activity: recent competitor moves → delay pricing
3. Past failure match: similar conditions failed before → delay/modify
4. System stability: unhealthy system → restrict to low-risk
5. Financial constraint: no cash → don't spend
6. Cooldown: too soon since similar action → delay

Verdict: proceed | delay | modify | escalate_to_human

Wave 2 #2 extension
-------------------
``JudgmentAdvisor`` now accepts an optional :class:`core.mentality.Values`
instance. When provided, each check's base weight is multiplied by the
principle multiplier for that check (see ``Values.check_multiplier``)
so tenants with different operator values (safety-first vs.
speed-first) get a gate that reflects their priorities without
touching the check implementations themselves.

A lightweight :class:`core.mentality.BeliefStore` is also attached for
Bayesian belief updates. ``update_belief`` lets callers feed binary
outcomes (``"price_cut::product_123"`` → success/failure) into the
gate and ``get_belief_mean`` exposes the current posterior mean for
any decision path that wants to consult it.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from utils.logger import get_logger

if TYPE_CHECKING:
    from core.mentality import BeliefStore, Values

logger = get_logger("judgment.advisor")


# Verdict thresholds
PROCEED_THRESHOLD = 0.70    # Risk score below this → proceed
DELAY_THRESHOLD = 0.85      # Between proceed and delay → delay
# Above delay → escalate


class JudgmentAdvisor:
    """Pre-execution judgment gate.

    Usage:
        advisor = JudgmentAdvisor(
            episodic_memory=memory,
            failure_prevention=failure_prev,
            action_coordinator=coordinator,
        )
        verdict = advisor.evaluate(decision, snapshot_situation)
        if verdict["verdict"] != "proceed":
            # don't execute
    """

    def __init__(
        self,
        episodic_memory: Any = None,
        failure_prevention: Any = None,
        action_coordinator: Any = None,
        values: "Values | None" = None,
        belief_store: "BeliefStore | None" = None,
    ) -> None:
        self._memory = episodic_memory
        self._failure_prevention = failure_prevention
        self._action_coordinator = action_coordinator
        self._values = values

        # Lazy-construct an empty BeliefStore when not supplied so
        # callers can always call ``update_belief`` without an
        # extra wiring step.
        if belief_store is None:
            try:
                from core.mentality import BeliefStore as _BS
                belief_store = _BS()
            except Exception:  # pragma: no cover - defensive
                belief_store = None
        self._beliefs = belief_store

    # Default check weights — kept in sync with what each
    # `_check_*` method returns. Used as the fail-safe weight when
    # a check method raises and we synthesize a stub result.
    _CHECK_DEFAULTS: dict[str, float] = {
        "magnitude":            0.20,
        "competitor_activity":  0.15,
        "past_failures":        0.25,
        "system_stability":     0.15,
        "financial_constraint": 0.15,
        "cooldown":             0.10,
        # Wave 6 #3: belief-informed past-success check. Fail-safe
        # weight is 0.0 — a crashing check must not suddenly start
        # penalising actions that have no prior evidence, since the
        # posterior is still silent on them.
        "belief_posterior":     0.00,
    }

    def _safe_check(
        self,
        name: str,
        fn,
        *args,
    ) -> dict[str, Any]:
        """Run a single check behind a try/except so a buggy
        downstream module can't take down the entire vote.

        Fix O: on failure the stub returns ``risk=1.0`` (max
        uncertainty) and ``degraded=True``. Pre-fix this
        defaulted to ``risk=0.0`` which silently APPROVED
        decisions the gate couldn't verify — a safety gate
        that can't assess risk must treat that as high risk,
        not zero risk. The ``degraded`` flag lets
        ``evaluate()`` force a minimum verdict of ``delay``
        so blind checks can't coast through on other low
        signals.
        """
        try:
            result = fn(*args)
            if not isinstance(result, dict):
                raise TypeError(
                    f"check {name!r} returned {type(result).__name__}, expected dict"
                )
            # Defensive defaults so the consensus loop never crashes
            # on a check that forgot a key.
            result.setdefault("check", name)
            result.setdefault("risk", 0.0)
            result.setdefault("weight", self._CHECK_DEFAULTS.get(name, 0.10))
            result.setdefault("reason", f"{name}: no detail")
            return result
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "JudgmentAdvisor: check %r raised %s: %s — "
                "treating as DEGRADED (risk=1.0)",
                name, type(exc).__name__, exc,
            )
            return {
                "check": name,
                "risk": 1.0,
                "weight": self._CHECK_DEFAULTS.get(name, 0.10),
                "reason": f"{name}: check failed ({type(exc).__name__}) — signal unavailable",
                "error": str(exc)[:120],
                "degraded": True,
            }

    def evaluate(
        self,
        decision: dict[str, Any],
        situation: dict[str, Any],
    ) -> dict[str, Any]:
        """Evaluate whether to proceed with a decision.

        Args:
            decision: From IntelligenceLoop (action, confidence, confidence_score, etc.)
            situation: From StoreSnapshot.get_situation()

        Returns:
            {
                "verdict": "proceed" | "delay" | "modify" | "escalate_to_human",
                "risk_score": float (0-1),
                "checks": [...],
                "reason": str,
                "recommendations": [...],
            }
        """
        checks = [
            self._safe_check("magnitude", self._check_magnitude, decision),
            self._safe_check("competitor_activity", self._check_competitor_activity, decision, situation),
            self._safe_check("past_failures", self._check_past_failures, decision, situation),
            self._safe_check("system_stability", self._check_system_stability, situation),
            self._safe_check("financial_constraint", self._check_financial_constraint, decision, situation),
            self._safe_check("cooldown", self._check_cooldown, decision),
            # Wave 6 #3: read the Bayesian posterior fed by
            # _update_beliefs_from_execution so historical
            # success rates bend the gate.
            self._safe_check("belief_posterior", self._check_belief_posterior, decision),
        ]

        # Wave 2 #2: re-weight each check by the operator's
        # :class:`Values` multiplier so mentality propagates into
        # the risk score. No-op when values is None.
        if self._values is not None:
            for c in checks:
                base = c.get("weight", 0.0)
                effective = self._values.effective_check_weight(
                    c.get("check", ""), float(base),
                )
                c["base_weight"] = base
                c["weight"] = effective

        # Compute weighted risk score
        total_weight = sum(c["weight"] for c in checks)
        risk_score = sum(c["risk"] * c["weight"] for c in checks) / max(total_weight, 0.01)

        degraded = [c for c in checks if c.get("degraded")]
        degraded_count = len(degraded)

        # Determine verdict
        if any(c.get("veto") for c in checks):
            verdict = "escalate_to_human"
            # Use .get so a vetoing check that forgot to set "reason"
            # can't take down the whole evaluation with a KeyError.
            reason = next(
                (c.get("reason", "veto: no reason given") for c in checks if c.get("veto")),
                "veto: no reason given",
            )
        elif risk_score >= DELAY_THRESHOLD:
            verdict = "escalate_to_human"
            top_risks = sorted(checks, key=lambda c: c["risk"], reverse=True)[:2]
            reason = "; ".join(c.get("reason", "") for c in top_risks if c["risk"] > 0.5)
        elif risk_score >= PROCEED_THRESHOLD:
            verdict = "delay"
            top_risks = sorted(checks, key=lambda c: c["risk"], reverse=True)[:2]
            reason = "; ".join(c.get("reason", "") for c in top_risks if c["risk"] > 0.3)
        else:
            verdict = "proceed"
            reason = "All checks passed"

        # Fix O fail-safe ratchet: degraded (failed-to-run)
        # checks can't coast through on other low signals.
        # One degraded check bumps the minimum verdict to
        # "delay"; two or more force "escalate_to_human"
        # since the gate itself looks broken.
        if degraded_count >= 2 and verdict == "proceed":
            verdict = "escalate_to_human"
        elif degraded_count >= 2:
            verdict = "escalate_to_human"
        elif degraded_count == 1 and verdict == "proceed":
            verdict = "delay"
        if degraded_count:
            degraded_names = ", ".join(c["check"] for c in degraded)
            reason = (
                f"{degraded_count} check(s) degraded [{degraded_names}]"
                + (f"; {reason}" if reason else "")
            )

        recommendations = [c.get("recommendation", "") for c in checks if c.get("recommendation")]

        logger.info(
            "Judgment: %s (risk=%.2f, degraded=%d) for action '%s'",
            verdict, risk_score, degraded_count,
            decision.get("action", "?")[:50],
        )

        return {
            "verdict": verdict,
            "risk_score": round(risk_score, 3),
            "checks": checks,
            "reason": reason,
            "recommendations": [r for r in recommendations if r],
            "degraded_checks": degraded_count,
        }

    # ── Wave 3 #2: advisor + debate integration ────────────────────

    def deliberate(
        self,
        decision: dict[str, Any],
        situation: dict[str, Any],
        *,
        memories: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Evaluate, then optionally run multi-agent debate.

        When :meth:`evaluate` lands a decision cleanly in the
        proceed/escalate regions (``risk_score`` outside
        ``[PROCEED_THRESHOLD, DELAY_THRESHOLD]``), the verdict is
        unambiguous and debate adds nothing — ``deliberate`` just
        returns the advisor payload with ``debate=None``.

        Inside the uncertainty band the 5-persona debate (Wave 2
        #8) runs, scoring each proposal against the advisor's
        :class:`~core.mentality.Values` so the operator's
        priorities carry the tiebreak. The chosen proposal and
        full scoring breakdown are attached to the return payload
        under a ``debate`` key.

        The debate layer is imported lazily and any failure in it
        is captured so a broken persona can't take down the gate.

        Args:
            decision: Same as :meth:`evaluate`.
            situation: Same as :meth:`evaluate`.
            memories: Optional list of prior case dicts for the
                ``MemoryManager`` persona. Each entry should at
                minimum carry a ``success: bool`` field so the
                precedent ratio is computable.

        Returns:
            The full :meth:`evaluate` payload extended with a
            ``debate`` key. ``debate`` is either ``None`` (outside
            the band, debate disabled, or debate crashed) or a
            :meth:`DebateOutcome.as_dict` dict carrying the winning
            persona, summary, scored breakdown, and trigger flag.
        """
        result = self.evaluate(decision, situation)

        # Lazy imports so a deployment without the brain layer
        # still uses the plain advisor path without import errors.
        try:
            from core.brain.debate import (
                DebateArbiter,
                DebateContext,
                should_debate,
            )
        except Exception as exc:  # pragma: no cover - import guard
            logger.debug("deliberate: debate module unavailable: %s", exc)
            result["debate"] = None
            return result

        risk = float(result.get("risk_score") or 0.0)
        if not should_debate(risk):
            result["debate"] = None
            return result

        # Always give the arbiter concrete Values — either the
        # advisor's (which already shaped the risk score) or a
        # neutral default so safety-oriented tie-breaks still work.
        values = self._values
        if values is None:
            try:
                from core.mentality import Values as _V
                values = _V()
            except Exception:  # pragma: no cover - defensive
                result["debate"] = None
                return result

        try:
            arbiter = DebateArbiter(values=values)
            outcome = arbiter.run(
                DebateContext(
                    decision=dict(decision),
                    situation=dict(situation),
                    advisor_result=result,
                    memories=list(memories or []),
                ),
            )
            result["debate"] = outcome.as_dict()
            logger.info(
                "Judgment deliberate: risk=%.2f in band → debate winner=%s",
                risk, outcome.winner.persona,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "JudgmentAdvisor.deliberate: debate failed %s: %s",
                type(exc).__name__, exc,
            )
            result["debate"] = None

        return result

    def _check_magnitude(self, decision: dict[str, Any]) -> dict[str, Any]:
        """Big change + low confidence → high risk."""
        confidence = decision.get("confidence_score", 50)
        options_evaluated = decision.get("options_evaluated", 1)

        risk = 0
        reason = "Normal magnitude"

        # Low confidence + few options = risky
        if confidence < 40:
            risk = 0.8
            reason = f"Very low confidence ({confidence}/100)"
        elif confidence < 60 and options_evaluated <= 2:
            risk = 0.5
            reason = f"Low confidence ({confidence}/100) with only {options_evaluated} options"
        elif confidence < 50:
            risk = 0.4
            reason = f"Below-average confidence ({confidence}/100)"

        return {
            "check": "magnitude",
            "risk": risk,
            "weight": 0.20,
            "reason": reason,
            "recommendation": "Collect more data before deciding" if risk > 0.5 else "",
        }

    def _check_competitor_activity(self, decision: dict[str, Any], situation: dict[str, Any]) -> dict[str, Any]:
        """Recent competitor activity → delay pricing decisions."""
        competitive = situation.get("competitive", {})
        alerts = competitive.get("alerts", []) if isinstance(competitive, dict) else []
        # Be defensive: callers occasionally pass `events: None` or
        # a malformed value here. Coerce to a list so the
        # comprehension below can't crash with TypeError.
        events_raw = situation.get("events", [])
        events = events_raw if isinstance(events_raw, list) else []
        if not isinstance(alerts, list):
            alerts = []

        risk = 0
        reason = "No competitor activity"

        competitor_events = [e for e in events if "competitor" in str(e).lower() or "price_change" in str(e).lower()]
        if competitor_events or alerts:
            action = decision.get("action", "")
            if "pric" in action.lower():
                risk = 0.7
                reason = f"Competitor activity detected ({len(competitor_events) + len(alerts)} signals) — risky to change prices now"
            else:
                risk = 0.3
                reason = f"Competitor activity detected but decision is not pricing-related"

        return {
            "check": "competitor_activity",
            "risk": risk,
            "weight": 0.15,
            "reason": reason,
        }

    def _check_past_failures(self, decision: dict[str, Any], situation: dict[str, Any]) -> dict[str, Any]:
        """Check if similar decision failed before in similar conditions."""
        if self._failure_prevention is None:
            return {"check": "past_failures", "risk": 0, "weight": 0.25, "reason": "No failure data"}

        # Build context for matching
        financial = situation.get("financial", {})
        inventory = situation.get("inventory", {})
        customers = situation.get("customers", {})
        health = situation.get("health", {})

        context = {
            "health_grade": financial.get("health_grade", health.get("overall_grade", "B")),
            "churn_pct": customers.get("churn_risk_pct", 0),
            "stockout_risk": inventory.get("stockout_risk", False),
            "confidence_score": decision.get("confidence_score", 50),
            "net_margin": financial.get("net_margin", 0),
            "critical_alerts": financial.get("critical_alerts", 0),
        }

        # Determine decision type from action string
        action = decision.get("action", "")
        decision_type = "general"
        if "pric" in action.lower():
            decision_type = "pricing"
        elif "launch" in action.lower():
            decision_type = "launch"
        elif "campaign" in action.lower() or "ad" in action.lower():
            decision_type = "marketing"

        result = self._failure_prevention.check(decision_type, context, action)

        risk = result.get("match_score", 0)
        if result.get("vetoed"):
            return {
                "check": "past_failures",
                "risk": 1.0,
                "weight": 0.25,
                "reason": result["reason"],
                "veto": True,
                "recommendation": "Avoid this action — past failure in similar conditions",
            }

        return {
            "check": "past_failures",
            "risk": risk,
            "weight": 0.25,
            "reason": result.get("reason", "No matching failures"),
            "recommendation": result.get("recommendation", ""),
        }

    def _check_system_stability(self, situation: dict[str, Any]) -> dict[str, Any]:
        """Unhealthy system → restrict to low-risk actions."""
        health = situation.get("health", {})
        grade = health.get("overall_grade", "B")

        risk = 0
        reason = f"System health: {grade}"

        if grade in ("D", "F"):
            risk = 0.7
            reason = f"System health is {grade} — only low-risk actions recommended"
        elif grade == "C":
            risk = 0.3
            reason = f"System health is {grade} — proceed with caution"

        return {
            "check": "system_stability",
            "risk": risk,
            "weight": 0.15,
            "reason": reason,
            "recommendation": "Fix system health issues first" if risk > 0.5 else "",
        }

    def _check_financial_constraint(self, decision: dict[str, Any], situation: dict[str, Any]) -> dict[str, Any]:
        """No cash → don't spend money."""
        financial = situation.get("financial", {})
        health_grade = financial.get("health_grade", "B")
        critical = financial.get("critical_alerts", 0)

        action = decision.get("action", "")
        costs_money = any(kw in action.lower() for kw in ("ad", "campaign", "spend", "buy", "launch", "reorder"))

        risk = 0
        reason = "Financial position OK"

        if costs_money and (health_grade in ("D", "F") or critical > 0):
            risk = 0.8
            reason = f"Action requires spending but financial health is {health_grade} with {critical} critical alerts"
        elif health_grade in ("D", "F"):
            risk = 0.4
            reason = f"Financial health is {health_grade}"

        return {
            "check": "financial_constraint",
            "risk": risk,
            "weight": 0.15,
            "reason": reason,
            "recommendation": "Improve margins before spending" if risk > 0.5 else "",
        }

    def _check_cooldown(self, decision: dict[str, Any]) -> dict[str, Any]:
        """Check action cooldowns."""
        if self._action_coordinator is None:
            return {"check": "cooldown", "risk": 0, "weight": 0.10, "reason": "No coordinator"}

        action = decision.get("action", "")
        # Map decision action to action_coordinator types
        action_type = "product_update"  # default
        if "pric" in action.lower() and "increase" in action.lower():
            action_type = "price_increase"
        elif "pric" in action.lower():
            action_type = "price_decrease"
        elif "ad" in action.lower() or "campaign" in action.lower():
            action_type = "ad_launch"

        verdict = self._action_coordinator.check(action_type)
        if not verdict["allowed"]:
            return {
                "check": "cooldown",
                "risk": 0.9,
                "weight": 0.10,
                "reason": f"Cooldown active: {verdict['reason']}",
            }

        return {"check": "cooldown", "risk": 0, "weight": 0.10, "reason": "No cooldown issues"}

    # -- Wave 6 #3: belief-informed past-success check ----------------

    # Minimum number of observations before the posterior is allowed
    # to influence the gate. Smaller samples are too noisy — they'd
    # let a single lucky/unlucky run swing the verdict.
    _BELIEF_MIN_OBSERVATIONS = 3

    # Active weight applied once the posterior has enough evidence.
    # Mirrors the other "soft signal" checks (competitor, financial).
    _BELIEF_ACTIVE_WEIGHT = 0.15

    def _check_belief_posterior(self, decision: dict[str, Any]) -> dict[str, Any]:
        """Query the Bayesian posterior for this decision's key.

        Wave 6 #2 wired :meth:`update_belief` into the orchestrator's
        execution phase so every cycle feeds success/failure outcomes
        into the belief store with key ``"<target>::<action_type>"``.
        Wave 6 #3 closes that loop: this check reads the posterior
        for the same key and raises risk when the historical success
        rate is low.

        The check is silent (``weight=0``) until at least
        :attr:`_BELIEF_MIN_OBSERVATIONS` outcomes have been recorded
        — under that threshold the posterior is too noisy to trust
        and contributing to the weighted risk score would just add
        jitter. This also means decisions without any prior history
        see exactly zero delta versus the pre-Wave-6 gate, so
        existing behaviour is preserved end-to-end.
        """
        silent = {
            "check":  "belief_posterior",
            "risk":   0.0,
            "weight": 0.0,
        }

        if self._beliefs is None:
            return {**silent, "reason": "No belief store attached"}

        target = decision.get("target") or "unknown"
        action_type = decision.get("action_type") or "unknown"
        key = f"{target}::{action_type}"

        belief = self._beliefs.get(key)
        if belief is None:
            return {**silent, "reason": f"No prior outcomes for {key}"}

        n = belief.n
        mean = belief.mean
        if n < self._BELIEF_MIN_OBSERVATIONS:
            return {
                **silent,
                "reason": (
                    f"Insufficient history for {key} "
                    f"(n={n}, mean={mean:.2f})"
                ),
            }

        # Linear mapping: mean=1.0 → risk=0, mean=0.0 → risk=1.0
        risk = max(0.0, min(1.0, 1.0 - mean))

        recommendation = ""
        if risk >= 0.5:
            recommendation = (
                f"Historical success for {key} is "
                f"{int(round(mean * 100))}% over {n} run(s) — "
                f"consider a safer alternative or more evidence"
            )

        return {
            "check":          "belief_posterior",
            "risk":           round(risk, 3),
            "weight":         self._BELIEF_ACTIVE_WEIGHT,
            "reason":         (
                f"Posterior success rate for {key}: "
                f"{mean:.2f} (n={n})"
            ),
            "recommendation": recommendation,
        }

    # -- Wave 2 #2: belief accessors ----------------------------------

    def update_belief(
        self,
        key: str,
        success: bool,
        weight: float = 1.0,
    ) -> dict[str, Any] | None:
        """Record a success/failure observation for *key*.

        Returns the updated belief snapshot (alpha, beta, mean, n)
        or ``None`` if the advisor has no belief store attached.

        This is the hook the learning loop and reflection synthesizer
        use to feed outcomes into the gate's Bayesian posterior. The
        advisor itself doesn't consult the posterior during
        ``evaluate`` — that's the caller's job — but it does provide
        a single thread-safe home for the beliefs so they can be
        snapshotted, persisted, or debugged from one place.
        """
        if self._beliefs is None:
            return None
        belief = self._beliefs.observe(key, success, weight=weight)
        return {
            "key":   belief.key,
            "alpha": belief.alpha,
            "beta":  belief.beta,
            "mean":  belief.mean,
            "n":     belief.n,
        }

    def get_belief_mean(
        self, key: str, default: float = 0.5,
    ) -> float:
        """Return the posterior mean for *key* (or *default*)."""
        if self._beliefs is None:
            return default
        return self._beliefs.mean(key, default=default)

    def get_belief_interval(
        self, key: str,
    ) -> tuple[float, float]:
        """Return the 95% credible interval for *key*."""
        if self._beliefs is None:
            return (0.0, 1.0)
        return self._beliefs.credible_interval_95(key)
