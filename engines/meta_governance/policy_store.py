"""Tiered policy store — next-level governance on top of the
hardcoded policy checker.

Wave 2 #1 upgrade: the existing ``policy_checker.check_policies()``
enforces 6 immutable safety rules (POL-001..POL-006). Those stay
intact. This module adds everything that was *missing*:

* **Tiering.** Rules are classified ``HARD`` (immutable safety),
  ``MEDIUM`` (versioned operator rules), or ``SOFT`` (learned
  heuristics promoted by the reflection synthesizer).
* **Verdicts.** Instead of boolean ``passed``, each rule returns
  ``ALLOW`` / ``MODIFY`` / ``BLOCK`` with a reason trace. ``MODIFY``
  rules can patch the action before downstream execution.
* **Versioning.** Every non-HARD rule carries a ``version`` that
  bumps on edit, so audit records can be correlated with the exact
  rule that fired.
* **Audit log.** Every evaluation appends a JSONL record to
  ``.audit/policy_audit.jsonl`` (rule id, tier, version, verdict,
  modifications, inputs hash). This is per-decision granularity —
  the existing ``audit_logger.log_audit_entry`` still records the
  full governance pipeline outcome at a higher level.
* **Rule promotion.** ``PolicyStore.promote_soft_rule()`` is the
  entry point Wave 2 #5 will call when the reflection synthesizer
  confirms a recurring error pattern.

Integration contract
--------------------
``evaluate_tiered(action, context)`` is the one call external
callers should use. It runs the HARD batch from the existing
``policy_checker`` first, then the store's MEDIUM and SOFT rules.
If anything returns BLOCK the decision halts; otherwise MODIFY
patches are accumulated and the action is returned alongside the
final verdict.

This module does NOT modify ``policy_checker.py`` — the hardcoded
rules are wrapped, not rewritten. Existing tests stay green.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from threading import Lock as _Lock, RLock
from typing import Any, Callable

from utils.logger import get_logger

from .policy_checker import check_policies

logger = get_logger("meta_governance.policy_store")


# ---------------------------------------------------------------------------
# Enums & dataclasses
# ---------------------------------------------------------------------------


class PolicyTier(str, Enum):
    """Rule tiers in descending authority order.

    ``HARD`` rules are the immutable safety baseline — the 6
    POL-xxx checks from ``policy_checker.py``. They cannot be
    removed or reordered; only edited at source.

    ``MEDIUM`` rules are versioned operator rules. Examples:
    per-tenant spending caps, per-market content blocks,
    scheduled maintenance freezes. These can be added, edited,
    or removed at runtime via :class:`PolicyStore`.

    ``SOFT`` rules are learned heuristics promoted by the
    reflection synthesizer when an error pattern recurs at least
    ``N`` times in the configured window. They carry the lowest
    authority and can be overridden by HARD/MEDIUM.
    """

    HARD = "hard"
    MEDIUM = "medium"
    SOFT = "soft"


class PolicyVerdict(str, Enum):
    """Outcome of a rule (or full evaluation)."""

    ALLOW = "allow"
    MODIFY = "modify"
    BLOCK = "block"


# Matcher/modifier function signatures kept loose so rules can be
# registered from plain Python without boilerplate.
MatcherFn = Callable[[dict[str, Any], dict[str, Any]], bool]
ModifyFn = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]


@dataclass
class PolicyRule:
    """A single tiered policy rule.

    ``matcher(action, context) -> bool`` decides whether the rule
    fires. If it does, ``verdict`` is applied. For ``MODIFY``
    rules, ``modify_fn(action, context) -> patch_dict`` produces
    the field patch to merge into the action.
    """

    rule_id: str
    name: str
    tier: PolicyTier
    source: str                       # "hardcoded" | "operator" | "learned"
    description: str
    matcher: MatcherFn
    verdict: PolicyVerdict = PolicyVerdict.BLOCK
    modify_fn: ModifyFn | None = None
    version: int = 1
    created_at: str = field(
        default_factory=lambda: time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(),
        ),
    )
    # Wave 7c (GAP-8): optional serialisable matcher spec for rules
    # that need to survive a restart. When set, the rehydration
    # logic can rebuild the matcher from these fields instead of
    # requiring the caller to re-register with a live callable.
    # ``match_field`` names the action dict key to inspect;
    # ``match_pattern`` is a regex applied to its string value.
    match_field: str | None = None
    match_pattern: str | None = None

    def to_audit_dict(self) -> dict[str, Any]:
        """Serialise the rule metadata (not the callables) for
        the audit log."""
        d: dict[str, Any] = {
            "rule_id":       self.rule_id,
            "name":          self.name,
            "tier":          self.tier.value,
            "version":       self.version,
            "source":        self.source,
            "verdict":       self.verdict.value,
            "created_at":    self.created_at,
        }
        if self.match_field is not None:
            d["match_field"] = self.match_field
        if self.match_pattern is not None:
            d["match_pattern"] = self.match_pattern
        return d


@dataclass
class PolicyDecision:
    """Result of :meth:`PolicyStore.evaluate_tiered`.

    ``verdict`` is the final ``ALLOW``/``MODIFY``/``BLOCK`` after
    all tiers have run. ``trace`` is the per-rule list of
    metadata + match outcome + any modifications. ``final_rule_id``
    names the rule that drove the final verdict (the BLOCKing
    rule, or the last MODIFY rule). ``action`` is the final
    (possibly patched) action dict.
    """

    verdict: PolicyVerdict
    action: dict[str, Any]
    modifications: dict[str, Any]
    trace: list[dict[str, Any]]
    final_rule_id: str | None
    final_tier: PolicyTier | None
    hard_passed: bool                 # whether HARD batch cleared
    failed_count: int                 # HARD checks failed

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict":       self.verdict.value,
            "action":        self.action,
            "modifications": self.modifications,
            "trace":         self.trace,
            "final_rule_id": self.final_rule_id,
            "final_tier":    self.final_tier.value if self.final_tier else None,
            "hard_passed":   self.hard_passed,
            "failed_count":  self.failed_count,
        }


# ---------------------------------------------------------------------------
# Policy store
# ---------------------------------------------------------------------------


_DEFAULT_AUDIT_PATH = os.path.join(
    os.path.dirname(__file__), ".audit", "policy_audit.jsonl",
)


class PolicyStore:
    """Thread-safe tiered rule registry with audit logging.

    The store holds MEDIUM and SOFT rules in memory and provides
    ``evaluate_tiered`` which combines them with the immutable
    HARD batch from ``policy_checker.check_policies``.

    Wave 7c (GAP-8): MEDIUM rules with serialisable matchers
    (``match_field`` + ``match_pattern``) can now survive restarts
    via a JSONL ledger file. Pass ``medium_ledger_path`` to enable.
    Rules that use custom callables remain memory-only.
    """

    def __init__(
        self,
        audit_path: str | None = None,
        medium_ledger_path: str | None = None,
    ) -> None:
        self._lock = RLock()
        self._rules: dict[PolicyTier, list[PolicyRule]] = {
            PolicyTier.HARD:   [],   # reserved; HARD runs via check_policies
            PolicyTier.MEDIUM: [],
            PolicyTier.SOFT:   [],
        }
        self._audit_path = audit_path or _DEFAULT_AUDIT_PATH
        # Wave 7c (GAP-8): optional MEDIUM rules ledger. When set,
        # operator MEDIUM rules with serialisable matchers survive
        # restarts. Rules without match_field/match_pattern are
        # kept in memory only (same as before).
        self._medium_ledger_path: str | None = medium_ledger_path
        # Wave 6 #8: per-rule activation counters so operators can
        # tell dead learned rules from useful ones.
        self._rule_stats: dict[str, dict[str, Any]] = {}
        # Rehydrate persisted MEDIUM rules
        if self._medium_ledger_path is not None:
            self._rehydrate_medium_rules()

    # -- registration --------------------------------------------------

    def register(self, rule: PolicyRule) -> str:
        """Register a new rule and return its rule_id.

        HARD tier registration is rejected — HARD rules live in
        ``policy_checker.py`` by design. Use the ``source`` field
        on MEDIUM/SOFT rules to distinguish operator-added vs
        learned rules.
        """
        if rule.tier == PolicyTier.HARD:
            raise ValueError(
                "HARD rules are immutable and live in policy_checker.py; "
                "register MEDIUM or SOFT rules here.",
            )
        with self._lock:
            # Replace existing rule with the same id (edit) and
            # bump the version so the audit log can tell them
            # apart.
            existing = [
                r for r in self._rules[rule.tier] if r.rule_id == rule.rule_id
            ]
            if existing:
                rule.version = max(r.version for r in existing) + 1
                self._rules[rule.tier] = [
                    r for r in self._rules[rule.tier]
                    if r.rule_id != rule.rule_id
                ]
            self._rules[rule.tier].append(rule)
            logger.info(
                "Policy rule registered: %s (tier=%s, version=%d, source=%s)",
                rule.rule_id, rule.tier.value, rule.version, rule.source,
            )
            # Wave 6 #13: audit the registration event.
            event = "PROMOTION" if rule.source == "learned" else "REGISTRATION"
            self._write_lifecycle_audit(event=event, rule=rule)
            # Wave 7c (GAP-8): persist MEDIUM rules to disk.
            if rule.tier == PolicyTier.MEDIUM:
                self._persist_medium_rules()
        return rule.rule_id

    def remove(self, rule_id: str) -> bool:
        """Remove a non-HARD rule by id. Returns True if removed.

        Wave 6 #13: emits a ``RETIREMENT`` lifecycle audit entry so
        that operator dashboards / the ``/api/policy/audit`` endpoint
        can track when and why a rule was retired (typically by the
        reflection auto-decay hook).
        """
        with self._lock:
            for tier in (PolicyTier.MEDIUM, PolicyTier.SOFT):
                before = len(self._rules[tier])
                removed_rules = [
                    r for r in self._rules[tier] if r.rule_id == rule_id
                ]
                if not removed_rules:
                    continue
                self._rules[tier] = [
                    r for r in self._rules[tier] if r.rule_id != rule_id
                ]
                if len(self._rules[tier]) < before:
                    rule = removed_rules[0]
                    logger.info(
                        "Policy rule removed: %s (tier=%s)",
                        rule_id, tier.value,
                    )
                    # Wave 6 #13: audit the removal so the trail is
                    # complete. Stats at time of removal are included
                    # so operators can see how active the rule was.
                    stats = self._rule_stats.get(rule_id) or {}
                    self._write_lifecycle_audit(
                        event="RETIREMENT",
                        rule=rule,
                        extra={
                            "matches":  stats.get("matches", 0),
                            "blocks":   stats.get("blocks", 0),
                            "last_matched_at": stats.get(
                                "last_matched_at",
                            ),
                        },
                    )
                    # Wave 7c (GAP-8): update ledger after removal.
                    if tier == PolicyTier.MEDIUM:
                        self._persist_medium_rules()
                    return True
        return False

    def promote_soft_rule(self, rule: PolicyRule) -> str:
        """Promote a learned rule to SOFT tier.

        This is the hook Wave 2 #5 (reflection synthesizer) calls
        when a recurring error pattern is confirmed. The rule's
        tier is coerced to SOFT and its source to ``"learned"``.
        """
        promoted = PolicyRule(
            rule_id=rule.rule_id,
            name=rule.name,
            tier=PolicyTier.SOFT,
            source="learned",
            description=rule.description,
            matcher=rule.matcher,
            verdict=rule.verdict,
            modify_fn=rule.modify_fn,
            version=rule.version,
        )
        return self.register(promoted)

    def list_rules(
        self, tier: PolicyTier | None = None,
    ) -> list[PolicyRule]:
        with self._lock:
            if tier is None:
                return [
                    r
                    for tier_rules in self._rules.values()
                    for r in tier_rules
                ]
            return list(self._rules[tier])

    def bump_version(self, rule_id: str) -> int | None:
        """Bump the version of a non-HARD rule. Returns new
        version, or None if the rule was not found."""
        with self._lock:
            for tier in (PolicyTier.MEDIUM, PolicyTier.SOFT):
                for r in self._rules[tier]:
                    if r.rule_id == rule_id:
                        r.version += 1
                        return r.version
        return None

    # -- evaluation ----------------------------------------------------

    def evaluate_tiered(
        self,
        action: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> PolicyDecision:
        """Run HARD → MEDIUM → SOFT rules against *action*.

        Pipeline:

        1. HARD batch via ``policy_checker.check_policies``. If
           any HARD check fails the decision is immediately
           ``BLOCK`` — HARD rules cannot be overridden.
        2. MEDIUM rules in registration order. Each matching rule
           may ``BLOCK`` (stops evaluation), ``MODIFY`` (patches
           the action), or ``ALLOW`` (explicit pass).
        3. SOFT rules in registration order with the same
           semantics, but with the lowest authority.

        Returns a :class:`PolicyDecision` with the final verdict,
        the (possibly patched) action, and the full trace.
        """
        ctx = context or {}
        trace: list[dict[str, Any]] = []
        modifications: dict[str, Any] = {}
        current_action = dict(action)
        final_verdict = PolicyVerdict.ALLOW
        final_rule_id: str | None = None
        final_tier: PolicyTier | None = None

        # ---- Tier 1: HARD (wrap existing policy_checker) -----------
        hard_result = self._run_hard_batch(current_action, ctx)
        trace.append(hard_result)
        hard_passed = bool(hard_result.get("passed", False))
        failed_count = int(hard_result.get("failed_count", 0))

        if not hard_passed:
            final_verdict = PolicyVerdict.BLOCK
            final_rule_id = "HARD:policy_checker"
            final_tier = PolicyTier.HARD
            self._write_audit(
                action, ctx, trace, final_verdict,
                final_rule_id, modifications, final_tier,
            )
            return PolicyDecision(
                verdict=final_verdict,
                action=current_action,
                modifications=modifications,
                trace=trace,
                final_rule_id=final_rule_id,
                final_tier=final_tier,
                hard_passed=False,
                failed_count=failed_count,
            )

        # ---- Tiers 2 & 3: MEDIUM then SOFT -------------------------
        for tier in (PolicyTier.MEDIUM, PolicyTier.SOFT):
            with self._lock:
                rules = list(self._rules[tier])
            for rule in rules:
                try:
                    matched = bool(rule.matcher(current_action, ctx))
                except Exception as exc:  # noqa: BLE001
                    trace.append({
                        **rule.to_audit_dict(),
                        "matched": False,
                        "error": f"{type(exc).__name__}: {exc}",
                    })
                    continue

                if not matched:
                    continue

                # Wave 6 #8: record the match. BLOCK / MODIFY
                # outcomes are recorded later inside their own
                # branches so we can distinguish them from bare
                # ALLOW matches.
                self._record_match(rule, "matches")

                entry: dict[str, Any] = {
                    **rule.to_audit_dict(),
                    "matched": True,
                }

                if rule.verdict == PolicyVerdict.BLOCK:
                    self._record_match(rule, "blocks")
                    trace.append(entry)
                    final_verdict = PolicyVerdict.BLOCK
                    final_rule_id = rule.rule_id
                    final_tier = tier
                    self._write_audit(
                        action, ctx, trace, final_verdict,
                        final_rule_id, modifications, final_tier,
                    )
                    return PolicyDecision(
                        verdict=final_verdict,
                        action=current_action,
                        modifications=modifications,
                        trace=trace,
                        final_rule_id=final_rule_id,
                        final_tier=final_tier,
                        hard_passed=True,
                        failed_count=0,
                    )

                if rule.verdict == PolicyVerdict.MODIFY and rule.modify_fn:
                    patch_applied = False
                    try:
                        patch = rule.modify_fn(current_action, ctx) or {}
                        if isinstance(patch, dict) and patch:
                            current_action.update(patch)
                            modifications.update(patch)
                            entry["modifications"] = dict(patch)
                            patch_applied = True
                            self._record_match(rule, "modifications")
                    except Exception as exc:  # noqa: BLE001
                        entry["modify_error"] = (
                            f"{type(exc).__name__}: {exc}"
                        )
                    # Only upgrade the running verdict when a patch
                    # was actually applied — a failed / empty modify
                    # leaves the action untouched, so the verdict
                    # stays where it was (ALLOW by default).
                    if (
                        patch_applied
                        and final_verdict == PolicyVerdict.ALLOW
                    ):
                        final_verdict = PolicyVerdict.MODIFY
                        final_rule_id = rule.rule_id
                        final_tier = tier

                # ALLOW rules are explicit passes — recorded in the
                # trace but don't change the running verdict.
                trace.append(entry)

        self._write_audit(
            action, ctx, trace, final_verdict,
            final_rule_id, modifications, final_tier,
        )
        return PolicyDecision(
            verdict=final_verdict,
            action=current_action,
            modifications=modifications,
            trace=trace,
            final_rule_id=final_rule_id,
            final_tier=final_tier,
            hard_passed=True,
            failed_count=0,
        )

    # -- Wave 6 #8: rule activation stats -----------------------------

    def _record_match(
        self, rule: PolicyRule, bucket: str,
    ) -> None:
        """Bump the per-rule counter *bucket* and refresh timestamps.

        Called from :meth:`evaluate_tiered` every time a MEDIUM or
        SOFT rule's matcher returns True. Buckets are:

        * ``matches``       — any positive matcher hit
        * ``blocks``        — match that produced a BLOCK verdict
        * ``modifications`` — match that produced a successful MODIFY

        Failures inside this helper are swallowed — stat recording
        must never take down the evaluation pipeline.
        """
        try:
            now = time.time()
            with self._lock:
                row = self._rule_stats.get(rule.rule_id)
                if row is None:
                    row = {
                        "rule_id":         rule.rule_id,
                        "tier":            rule.tier.value,
                        "source":          rule.source,
                        "matches":         0,
                        "blocks":          0,
                        "modifications":   0,
                        "first_matched_at": now,
                        "last_matched_at":  now,
                    }
                    self._rule_stats[rule.rule_id] = row
                row[bucket] = int(row.get(bucket, 0)) + 1
                row["last_matched_at"] = now
                # Keep tier/source in sync if the rule was re-registered
                # (promote_soft_rule bumps version and can change tier).
                row["tier"] = rule.tier.value
                row["source"] = rule.source
        except Exception as exc:  # noqa: BLE001
            logger.debug("rule stats record failed: %s", exc)

    def get_rule_stats(self, rule_id: str) -> dict[str, Any] | None:
        """Return a copy of the stats for one rule, or ``None`` if
        the rule has never matched."""
        with self._lock:
            row = self._rule_stats.get(rule_id)
            return dict(row) if row is not None else None

    def get_all_rule_stats(self) -> list[dict[str, Any]]:
        """Return every stats row as a list of dicts sorted by
        ``matches`` descending.

        Rules that have never fired do not appear — callers can
        cross-reference with :meth:`list_rules` to find dead rules.
        """
        with self._lock:
            rows = [dict(r) for r in self._rule_stats.values()]
        rows.sort(
            key=lambda r: (-int(r.get("matches", 0)), r.get("rule_id", "")),
        )
        return rows

    def reset_rule_stats(self, rule_id: str | None = None) -> None:
        """Clear per-rule activation stats.

        With a ``rule_id`` only that entry is cleared; without one
        the entire stats table is wiped. Useful after operators
        retune a rule set and want a clean rolling window.
        """
        with self._lock:
            if rule_id is None:
                self._rule_stats.clear()
            else:
                self._rule_stats.pop(rule_id, None)

    # -- internals -----------------------------------------------------

    def _run_hard_batch(
        self,
        action: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Wrap the existing ``check_policies`` call into a single
        HARD-tier trace entry."""
        # ``check_policies`` expects an *activity* envelope with
        # ``action_details`` and ``action_type``. Map the raw
        # action dict to that shape so callers can pass the flat
        # action and not worry about the legacy wrapper format.
        activity = {
            "action_details": action,
            "action_type":    action.get("action_type", "unknown"),
        }
        result = check_policies(activity, context)
        checks = result.get("checks", [])
        all_passed = bool(result.get("all_passed", False))
        failed_count = int(result.get("failed_count", 0))

        return {
            "tier":         PolicyTier.HARD.value,
            "rule_id":      "HARD:policy_checker",
            "name":         "hardcoded_safety_batch",
            "source":       "hardcoded",
            "version":      1,
            "verdict":      (
                PolicyVerdict.ALLOW.value
                if all_passed
                else PolicyVerdict.BLOCK.value
            ),
            "matched":      True,
            "passed":       all_passed,
            "failed_count": failed_count,
            "checks":       checks,
        }

    def _write_audit(
        self,
        action: dict[str, Any],
        context: dict[str, Any],
        trace: list[dict[str, Any]],
        verdict: PolicyVerdict,
        final_rule_id: str | None,
        modifications: dict[str, Any],
        final_tier: PolicyTier | None,
    ) -> None:
        """Append a JSONL audit record. Write errors are logged
        but swallowed — the hot path must never die because the
        audit disk is unavailable."""
        try:
            os.makedirs(
                os.path.dirname(self._audit_path), exist_ok=True,
            )
            entry = {
                "entry_id":      uuid.uuid4().hex[:12],
                "timestamp":     time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(),
                ),
                "verdict":       verdict.value,
                "final_rule_id": final_rule_id,
                "final_tier":    (
                    final_tier.value if final_tier else None
                ),
                "modifications": modifications,
                "trace":         trace,
                "action_type":   action.get("action_type"),
                "source_engine": context.get("source_engine", "unknown"),
                "inputs_hash":   _hash_inputs(action, context),
            }
            with open(self._audit_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, default=str) + "\n")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Policy audit write failed: %s", exc)

    # ── Wave 7c (GAP-8): MEDIUM rule persistence ───────────────

    def _persist_medium_rules(self) -> None:
        """Atomically rewrite the MEDIUM rules ledger.

        Only rules with ``match_field`` and ``match_pattern`` set
        are persisted — custom-callable rules remain memory-only.
        """
        if self._medium_ledger_path is None:
            return
        try:
            os.makedirs(
                os.path.dirname(self._medium_ledger_path), exist_ok=True,
            )
            import tempfile
            rules = self._rules[PolicyTier.MEDIUM]
            serialisable = [
                r for r in rules
                if r.match_field is not None and r.match_pattern is not None
            ]
            dir_name = os.path.dirname(self._medium_ledger_path)
            fd, tmp = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    for r in serialisable:
                        fh.write(json.dumps(r.to_audit_dict(), default=str) + "\n")
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp, self._medium_ledger_path)
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    # best-effort cleanup; raise the original
                    # write failure regardless.
                    pass
                raise
            logger.debug(
                "MEDIUM ledger: persisted %d rule(s) to %s",
                len(serialisable), self._medium_ledger_path,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("MEDIUM ledger persist failed: %s", exc)

    def _rehydrate_medium_rules(self) -> None:
        """Reload MEDIUM rules from the ledger at startup.

        Each line is a JSON dict with rule metadata plus
        ``match_field`` / ``match_pattern``. The matcher is
        rebuilt as a regex check on the named action field.
        """
        import re as _re

        path = self._medium_ledger_path
        if path is None or not os.path.exists(path):
            return
        loaded = 0
        skipped = 0
        try:
            with open(path, "r", encoding="utf-8") as fh:
                lines = fh.readlines()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "MEDIUM ledger: could not read %r (%s) — starting fresh",
                path, exc,
            )
            return
        existing_ids = {r.rule_id for r in self._rules[PolicyTier.MEDIUM]}
        for raw in lines:
            raw = raw.strip()
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                skipped += 1
                continue
            if not isinstance(row, dict):
                skipped += 1
                continue
            rule_id = row.get("rule_id")
            if not rule_id or rule_id in existing_ids:
                skipped += 1
                continue
            match_field = row.get("match_field")
            match_pattern = row.get("match_pattern")
            if not match_field or not match_pattern:
                skipped += 1
                continue
            try:
                compiled = _re.compile(match_pattern)
            except _re.error:
                skipped += 1
                continue
            # Rebuild the matcher from the serialised spec
            def _make_matcher(fld: str, pat: "_re.Pattern[str]"):
                def _matcher(action: dict, _ctx: dict) -> bool:
                    val = str(action.get(fld, ""))
                    return bool(pat.search(val))
                return _matcher

            try:
                rule = PolicyRule(
                    rule_id=rule_id,
                    name=row.get("name", rule_id),
                    tier=PolicyTier.MEDIUM,
                    source=row.get("source", "operator"),
                    description=row.get("description", ""),
                    matcher=_make_matcher(match_field, compiled),
                    verdict=PolicyVerdict(
                        row.get("verdict", PolicyVerdict.BLOCK.value),
                    ),
                    version=int(row.get("version", 1)),
                    created_at=row.get("created_at", ""),
                    match_field=match_field,
                    match_pattern=match_pattern,
                )
            except (KeyError, TypeError, ValueError):
                skipped += 1
                continue
            self._rules[PolicyTier.MEDIUM].append(rule)
            existing_ids.add(rule_id)
            loaded += 1
        if loaded or skipped:
            logger.info(
                "MEDIUM ledger: rehydrated %d rule(s) from %r (%d skipped)",
                loaded, path, skipped,
            )

    def _write_lifecycle_audit(
        self,
        event: str,
        rule: PolicyRule,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Append a lightweight lifecycle audit record.

        Wave 6 #13: ``_write_audit`` is shaped for evaluate_tiered
        verdicts (action → verdict → trace). Rule lifecycle events
        (registration, promotion, retirement) don't fit that shape
        so they get their own one-liner method. Same file, same
        fail-soft semantics.
        """
        try:
            os.makedirs(
                os.path.dirname(self._audit_path), exist_ok=True,
            )
            entry: dict[str, Any] = {
                "entry_id":  uuid.uuid4().hex[:12],
                "timestamp": time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(),
                ),
                "event":     event,
                **rule.to_audit_dict(),
            }
            if extra:
                entry["extra"] = extra
            with open(self._audit_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, default=str) + "\n")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Policy lifecycle audit write failed: %s", exc)

    def read_audit(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return the most recent audit entries (newest first).

        Wave 7 #6 (GAP-11): reads from the tail of the file
        instead of loading the entire JSONL into memory. The
        previous ``fh.readlines()`` approach would OOM on a busy
        production deployment where the audit file grows to
        hundreds of MB. The new approach seeks to the end and
        reads backwards in fixed-size chunks until enough lines
        are collected.
        """
        if not os.path.isfile(self._audit_path):
            return []
        try:
            return self._read_tail_lines(self._audit_path, limit)
        except OSError:
            return []

    @staticmethod
    def _read_tail_lines(
        path: str, limit: int, chunk_size: int = 8192,
    ) -> list[dict[str, Any]]:
        """Read the last *limit* parseable JSONL entries from *path*
        without loading the entire file.

        Seeks to the end, reads backwards in *chunk_size* byte
        chunks, splits on newlines, and parses from the tail until
        we have enough entries. Malformed lines are skipped.
        """
        entries: list[dict[str, Any]] = []
        with open(path, "rb") as fh:
            fh.seek(0, 2)  # seek to EOF
            remaining = fh.tell()
            if remaining == 0:
                return []
            buf = b""
            while remaining > 0 and len(entries) < limit:
                read_size = min(chunk_size, remaining)
                remaining -= read_size
                fh.seek(remaining)
                buf = fh.read(read_size) + buf
                # Split and process complete lines from the tail
                lines = buf.split(b"\n")
                # First element may be a partial line — keep it in buf
                buf = lines[0]
                # Process complete lines from newest (end) to oldest
                for raw in reversed(lines[1:]):
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        entries.append(json.loads(raw.decode("utf-8")))
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        continue
                    if len(entries) >= limit:
                        break
            # The leftover buf might be the very first line of the file
            if len(entries) < limit and buf.strip():
                try:
                    entries.append(json.loads(buf.strip().decode("utf-8")))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    # tolerate corrupt leading line; the rest
                    # of the file already loaded.
                    pass
        return entries


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _hash_inputs(
    action: dict[str, Any], context: dict[str, Any],
) -> str:
    """Short stable hash of the inputs, used to correlate audit
    records with replay inputs."""
    blob = json.dumps(
        {"a": action, "c": context},
        sort_keys=True,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


_default_store: PolicyStore | None = None
_default_store_lock = _Lock()


def get_default_store() -> PolicyStore:
    """Return the process-wide default :class:`PolicyStore`."""
    global _default_store
    if _default_store is None:
        with _default_store_lock:
            if _default_store is None:
                _default_store = PolicyStore()
    return _default_store


def reset_default_store() -> None:
    """Reset the module-level default store. Test-only hook."""
    global _default_store
    _default_store = None


def evaluate_tiered(
    action: dict[str, Any],
    context: dict[str, Any] | None = None,
    *,
    store: PolicyStore | None = None,
) -> PolicyDecision:
    """Convenience wrapper around :meth:`PolicyStore.evaluate_tiered`.

    Uses the process-wide default store when none is provided.
    """
    return (store or get_default_store()).evaluate_tiered(action, context)
