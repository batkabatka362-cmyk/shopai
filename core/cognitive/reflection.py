"""Reflection — meta-cognition over past decisions.

Where SelfModel says "here's what I am" and GoalManager says "here's
what I'm pursuing", Reflection is the loop that closes over them:

    1. Review the last N episodes from memory
    2. Identify patterns (recurring successes + failures)
    3. Score recent decision quality
    4. Update SelfModel (assess new signals)
    5. Revise GoalManager goals whose priority has shifted
    6. Emit a narrative lesson: "what I learned this cycle"

This is the "step back and think about my thinking" layer. It runs
on a schedule (every N cycles) rather than every cycle, because
the point of reflection is to see *trends*, not single events.

Inputs consumed:

    MemoryIntelligence episodes from the `action` / `decision` /
    `result` categories — provides the raw decision log
    SelfModel capabilities + narrative
    GoalManager active + recently-completed goals

Outputs emitted:

    Lessons — structured observations: {type, subject, evidence,
              confidence, recommended_action}
    SelfModel.assess() calls with the reflection source tag
    GoalManager.revise() calls when a goal's evidence has shifted
    A ReflectionReport dict the caller can log, display, or pass to
    the narrator / planner

Reflection types:

    strength       "You've been reliable at X for N cycles"
    weakness       "X has failed N times — investigate or abandon"
    improvement    "X went from 40% to 80% success"
    regression     "X went from 80% to 30% success"
    pattern        "Y tends to follow X"
    blind_spot     "You have no data about Z and it affects outcomes"

Reflection is cheap: no LLM calls required. The algorithms are
statistical (success rate deltas, co-occurrence counts, moving
averages) so they run deterministically.
"""
from __future__ import annotations

import statistics
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional

from utils.logger import get_logger

logger = get_logger("cognitive.reflection")


# Reflection thresholds
_MIN_EPISODES_FOR_TREND = 5   # need at least this many episodes to claim a trend
_TREND_DELTA = 0.25           # score change ≥ this counts as improvement/regression
_PATTERN_MIN_COUNT = 3        # need at least N co-occurrences to call it a pattern
_RECENT_WINDOW = 0.5          # split "recent" vs "older" at the 50th percentile
_REFLECTION_COOLDOWN_S = 60   # smallest gap between reflections (test fallback)


@dataclass
class Lesson:
    """A single observation produced by reflection."""
    type: str                       # strength | weakness | improvement | regression | pattern | blind_spot
    subject: str                    # capability or category name
    evidence: str                   # human-readable summary
    confidence: float               # 0-1
    score_before: Optional[float] = None
    score_after: Optional[float] = None
    recommended_action: str = ""    # what the AI should consider doing
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "subject": self.subject,
            "evidence": self.evidence,
            "confidence": round(self.confidence, 3),
            "score_before": self.score_before,
            "score_after": self.score_after,
            "recommended_action": self.recommended_action,
            "extra": self.extra,
        }


@dataclass
class ReflectionReport:
    """The full output of a reflection pass."""
    lessons: list[Lesson] = field(default_factory=list)
    episodes_reviewed: int = 0
    self_model_updates: int = 0
    goal_revisions: int = 0
    goals_created: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    narrative: str = ""
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "lessons": [l.to_dict() for l in self.lessons],
            "episodes_reviewed": self.episodes_reviewed,
            "self_model_updates": self.self_model_updates,
            "goal_revisions": self.goal_revisions,
            "goals_created": list(self.goals_created),
            "timestamp": self.timestamp,
            "narrative": self.narrative,
            "notes": list(self.notes),
        }


class Reflection:
    """Meta-cognitive reviewer.

    Two analysis layers stack on top of each other:

      1. Statistical detectors (trends, extremes, patterns,
         blind spots) — fast, deterministic, no LLM required.
      2. LLM-backed lesson generator — narrative insights from
         the LLM that catch nuance the statistical layer misses.
         Optional and gracefully skipped when no LLM is wired.

    Both layers contribute lessons to the same ReflectionReport.
    """

    def __init__(
        self,
        *,
        memory: Any = None,
        self_model: Any = None,
        goal_manager: Any = None,
        llm: Any = None,
        use_llm: bool = True,
    ) -> None:
        self._memory = memory
        self._self_model = self_model
        self._goal_manager = goal_manager
        self._llm = llm
        self._use_llm = bool(use_llm)
        self._last_reflection_ts: float = 0.0

    # ── Public API ─────────────────────────────────────────────

    def reflect(
        self,
        *,
        episode_limit: int = 100,
        category: str = "",
        apply: bool = True,
    ) -> ReflectionReport:
        """Run one reflection pass.

        Args:
            episode_limit: how many recent memory episodes to pull
            category: optional category filter (empty = all)
            apply: when True, updates SelfModel and revises goals as
                   a side effect. When False, the report is pure —
                   useful for "what would reflection say?" dry-runs.
        """
        report = ReflectionReport()
        episodes = self._fetch_episodes(episode_limit, category)
        report.episodes_reviewed = len(episodes)

        if not episodes:
            report.narrative = "No episodes to reflect on yet."
            return report

        # ─── Statistical analyses ───
        per_subject = self._group_by_subject(episodes)
        lessons: list[Lesson] = []
        lessons.extend(self._detect_trends(per_subject))
        lessons.extend(self._detect_consistent_extremes(per_subject))
        lessons.extend(self._detect_patterns(episodes))
        lessons.extend(self._detect_blind_spots())

        # ─── LLM-backed lesson generator (optional) ───
        if self._use_llm:
            llm_lessons = self._generate_llm_lessons(episodes)
            if llm_lessons:
                lessons.extend(llm_lessons)
                report.notes.append(f"+{len(llm_lessons)} LLM lessons")

        report.lessons = lessons

        # ─── Apply side effects ───
        if apply and self._self_model is not None:
            for lesson in lessons:
                if lesson.score_after is not None:
                    self._self_model.assess(
                        f"reflection.{lesson.subject}",
                        lesson.score_after,
                        evidence_count=1,
                        source="reflection",
                        notes=lesson.evidence[:200],
                    )
                    report.self_model_updates += 1

        if apply and self._goal_manager is not None:
            report.goal_revisions = self._revise_goals_from_lessons(lessons)
            report.goals_created = self._propose_goals_from_lessons(lessons)

        report.narrative = self._make_narrative(lessons, report.episodes_reviewed)
        self._last_reflection_ts = report.timestamp
        logger.info(
            "Reflection: %d episodes, %d lessons, %d SM updates, %d goal revisions",
            report.episodes_reviewed, len(lessons),
            report.self_model_updates, report.goal_revisions,
        )
        return report

    def last_reflection_ts(self) -> float:
        return self._last_reflection_ts

    # ── Episode fetching ───────────────────────────────────────

    def _fetch_episodes(
        self, limit: int, category: str,
    ) -> list[dict[str, Any]]:
        """Pull recent memory episodes to reflect on.

        Tolerates several shapes of memory backend — we try the
        MemoryIntelligence `retrieve()` API first, fall back to
        `get_all()` or similar, and finally return an empty list.
        """
        if self._memory is None:
            return []

        # Preferred: MemoryIntelligence.retrieve() — supports category filter
        retrieve = getattr(self._memory, "retrieve", None)
        if callable(retrieve):
            if category:
                try:
                    return list(retrieve(category=category, limit=limit) or [])
                except Exception:  # noqa: BLE001
                    pass
            else:
                # Without a category, collect a few domains commonly
                # used by the autonomous controller
                combined: list[dict[str, Any]] = []
                for cat in ("action", "decision", "result"):
                    try:
                        combined.extend(list(retrieve(
                            category=cat, limit=max(1, limit // 3),
                        ) or []))
                    except Exception:  # noqa: BLE001
                        continue
                if combined:
                    return combined[:limit]
                # Fall through to the generic fallback if every
                # category came back empty

        # Generic fallback for older / simpler memory backends
        for name in ("get_all", "all", "latest"):
            fn = getattr(self._memory, name, None)
            if callable(fn):
                try:
                    result = fn(limit=limit) if name != "all" else fn()
                    return list(result or [])[:limit]
                except Exception:  # noqa: BLE001
                    continue
        return []

    # ── Analyses ───────────────────────────────────────────────

    def _group_by_subject(
        self, episodes: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        """Group episodes by subject (action name + category fallback)."""
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for ep in episodes:
            subject = (
                ep.get("action")
                or ep.get("subject")
                or ep.get("category")
                or "unknown"
            )
            groups[str(subject)].append(ep)
        return groups

    def _raw_episode_score(self, ep: dict[str, Any]) -> Optional[float]:
        """Extract the raw score field (no scale normalization)."""
        raw = ep.get("score")
        if raw is None and isinstance(ep.get("result"), dict):
            raw = ep["result"].get("score")
        if raw is None:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalize_scores(raw_scores: list[float]) -> list[float]:
        """Detect 0-1 vs 1-5 scale from the batch and normalize to [0, 1].

        Heuristic: if any score in the batch is > 1.0, treat the whole
        batch as a 1-5 scale (matches MemoryIntelligence). Otherwise
        treat the scores as already normalized.

        This is per-batch so a single ambiguous 1.0 doesn't get
        misclassified — we look at peers for context.
        """
        if not raw_scores:
            return []
        max_s = max(raw_scores)
        if max_s > 1.0:
            return [
                max(0.0, min(1.0, (s - 1.0) / 4.0))
                for s in raw_scores
            ]
        return [max(0.0, min(1.0, s)) for s in raw_scores]

    def _episode_score(self, ep: dict[str, Any]) -> Optional[float]:
        """Backwards-compatible single-score extractor.

        Prefer _normalize_scores() at the group level for accurate
        scale detection. This method exists so external callers and
        the pattern detector can still get a per-episode score with
        a sensible default scale guess (assumes 1-5 if score > 1.0).
        """
        raw = self._raw_episode_score(ep)
        if raw is None:
            return None
        if raw > 1.0:
            return max(0.0, min(1.0, (raw - 1.0) / 4.0))
        return max(0.0, min(1.0, raw))

    def _detect_trends(
        self, per_subject: dict[str, list[dict[str, Any]]],
    ) -> list[Lesson]:
        """Find subjects whose average score has shifted significantly
        between the older half and the more recent half of episodes."""
        lessons: list[Lesson] = []
        for subject, eps in per_subject.items():
            if len(eps) < _MIN_EPISODES_FOR_TREND:
                continue

            # Sort by timestamp (oldest first) — tolerate missing ts
            eps_sorted = sorted(eps, key=lambda e: float(e.get("timestamp", 0) or 0))
            raw_scores = [self._raw_episode_score(e) for e in eps_sorted]
            raw_scores = [s for s in raw_scores if s is not None]
            scores = self._normalize_scores(raw_scores)
            if len(scores) < _MIN_EPISODES_FOR_TREND:
                continue

            split = int(len(scores) * _RECENT_WINDOW)
            if split < 1 or len(scores) - split < 1:
                continue

            older = scores[:split]
            recent = scores[split:]
            old_avg = statistics.mean(older)
            new_avg = statistics.mean(recent)
            delta = new_avg - old_avg

            if abs(delta) < _TREND_DELTA:
                continue

            if delta > 0:
                lessons.append(Lesson(
                    type="improvement",
                    subject=subject,
                    evidence=(
                        f"{subject} improved from {old_avg:.2f} to {new_avg:.2f} "
                        f"over {len(scores)} episodes"
                    ),
                    confidence=min(0.95, len(scores) / 20.0),
                    score_before=round(old_avg, 3),
                    score_after=round(new_avg, 3),
                    recommended_action="keep doing what's working",
                ))
            else:
                lessons.append(Lesson(
                    type="regression",
                    subject=subject,
                    evidence=(
                        f"{subject} regressed from {old_avg:.2f} to {new_avg:.2f} "
                        f"over {len(scores)} episodes"
                    ),
                    confidence=min(0.95, len(scores) / 20.0),
                    score_before=round(old_avg, 3),
                    score_after=round(new_avg, 3),
                    recommended_action="investigate recent changes",
                ))
        return lessons

    def _detect_consistent_extremes(
        self, per_subject: dict[str, list[dict[str, Any]]],
    ) -> list[Lesson]:
        """Subjects that are consistently high (strength) or low (weakness)."""
        lessons: list[Lesson] = []
        for subject, eps in per_subject.items():
            if len(eps) < _MIN_EPISODES_FOR_TREND:
                continue
            raw_scores = [self._raw_episode_score(e) for e in eps]
            raw_scores = [s for s in raw_scores if s is not None]
            scores = self._normalize_scores(raw_scores)
            if len(scores) < _MIN_EPISODES_FOR_TREND:
                continue
            avg = statistics.mean(scores)
            # Only flag when variance is low — i.e. *consistently* high/low
            try:
                spread = statistics.stdev(scores) if len(scores) >= 2 else 0.0
            except statistics.StatisticsError:
                spread = 0.0
            if spread > 0.25:
                continue  # too noisy to call this a trait

            if avg >= 0.8:
                lessons.append(Lesson(
                    type="strength",
                    subject=subject,
                    evidence=(
                        f"{subject} is consistently high: "
                        f"mean={avg:.2f}, spread={spread:.2f}, n={len(scores)}"
                    ),
                    confidence=min(0.95, len(scores) / 15.0),
                    score_after=round(avg, 3),
                    recommended_action="rely on this",
                ))
            elif avg <= 0.3:
                lessons.append(Lesson(
                    type="weakness",
                    subject=subject,
                    evidence=(
                        f"{subject} is consistently low: "
                        f"mean={avg:.2f}, spread={spread:.2f}, n={len(scores)}"
                    ),
                    confidence=min(0.95, len(scores) / 15.0),
                    score_after=round(avg, 3),
                    recommended_action="fix or abandon this path",
                ))
        return lessons

    def _detect_patterns(
        self, episodes: list[dict[str, Any]],
    ) -> list[Lesson]:
        """Find actions that tend to co-occur with specific outcomes.

        Simple co-occurrence: for each (action, outcome_category)
        pair, count how often they appear. When an action co-occurs
        with a "good" outcome ≥ _PATTERN_MIN_COUNT times, we emit
        a pattern lesson.
        """
        lessons: list[Lesson] = []
        outcomes: Counter[tuple[str, str]] = Counter()

        # Normalize all scores together so the scale is detected
        # from the full batch
        raw_pairs = [
            (ep, self._raw_episode_score(ep)) for ep in episodes
        ]
        raw_pairs = [(ep, s) for ep, s in raw_pairs if s is not None]
        if not raw_pairs:
            return lessons
        normalized = self._normalize_scores([s for _, s in raw_pairs])

        for (ep, _), score in zip(raw_pairs, normalized):
            action = str(ep.get("action") or "unknown")
            bucket = "positive" if score >= 0.6 else ("negative" if score <= 0.3 else "neutral")
            if bucket == "neutral":
                continue
            outcomes[(action, bucket)] += 1

        for (action, bucket), count in outcomes.most_common(20):
            if count < _PATTERN_MIN_COUNT or action == "unknown":
                continue
            opposite = (action, "negative" if bucket == "positive" else "positive")
            opposite_count = outcomes.get(opposite, 0)
            total = count + opposite_count
            if total == 0:
                continue
            ratio = count / total
            if ratio < 0.7:
                continue  # not reliable enough
            lessons.append(Lesson(
                type="pattern",
                subject=action,
                evidence=(
                    f"{action} leads to a {bucket} outcome "
                    f"{count}/{total} times ({ratio:.0%})"
                ),
                confidence=min(0.9, total / 10.0),
                score_after=ratio if bucket == "positive" else 1 - ratio,
                recommended_action=(
                    f"prefer {action}" if bucket == "positive"
                    else f"avoid {action}"
                ),
            ))
        return lessons

    def _detect_blind_spots(self) -> list[Lesson]:
        """Surface capabilities where SelfModel has very little data.

        This is subtly different from GoalManager's explore-goals: those
        pick one at a time to pursue, while reflection's blind-spot
        lessons are observations — the narrative layer uses them to
        tell the user "by the way, I have no data about X".
        """
        lessons: list[Lesson] = []
        if self._self_model is None:
            return lessons
        try:
            gaps = self._self_model.knowledge_gaps(top_n=5)
        except Exception:  # noqa: BLE001
            return lessons
        for g in gaps:
            name = g.get("name") if isinstance(g, dict) else None
            if not name:
                continue
            lessons.append(Lesson(
                type="blind_spot",
                subject=name,
                evidence=(
                    f"Only {g.get('evidence_count', 0)} observation(s) "
                    f"for {name} — I don't really know myself here"
                ),
                confidence=0.5,
                recommended_action="gather more data",
            ))
        return lessons

    # ── LLM-backed lesson generator ───────────────────────────

    def _generate_llm_lessons(
        self, episodes: list[dict[str, Any]],
    ) -> list[Lesson]:
        """Ask the LLM to read recent episodes and write narrative lessons.

        This is a layer ON TOP of the statistical detectors — it
        catches nuance the statistical layer misses (e.g. "the
        last 3 failures all happened on weekends" or "the
        successful runs all had high inventory"). The LLM gets
        the same episode list the statistical detectors saw.

        The output is a list of Lesson dataclasses with type
        prefixed by "llm:" so callers can tell them apart.

        Returns an empty list when:
            - No LLM is wired or available
            - The LLM returned a non-parseable response
            - The episodes list is too small to be worth asking
        """
        if len(episodes) < 3:
            return []

        llm = self._get_llm()
        if llm is None or not llm.is_available():
            return []

        try:
            from core.system.prompt_library import render_prompt
        except Exception:  # noqa: BLE001
            return []

        # Build a compact JSON view of episodes the LLM can read
        compact = []
        for ep in episodes[:30]:  # cap to keep token use sane
            compact.append({
                "action": ep.get("action") or ep.get("subject") or "?",
                "category": ep.get("category", ""),
                "score": ep.get("score"),
                "timestamp": ep.get("timestamp"),
            })
        try:
            import json
            episodes_json = json.dumps(compact, default=str)[:4000]
        except Exception:  # noqa: BLE001
            return []

        rendered = render_prompt(
            "reflection.summarize_episodes",
            episode_count=len(episodes),
            episodes_json=episodes_json,
        )
        if rendered is None:
            return []

        try:
            template = self._get_prompt_template("reflection.summarize_episodes")
            role = template.role if template else "analyzer"
            structured = llm.ask_structured(
                role=role,
                prompt=rendered.user,
                system_prompt=rendered.system,
                schema_hint=template.schema_hint if template else "",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Reflection LLM call failed: %s", exc)
            return []

        if not structured.ok:
            logger.debug(
                "Reflection LLM returned unparseable: %s",
                structured.error,
            )
            return []

        raw_lessons = structured.data.get("lessons") or []
        if not isinstance(raw_lessons, list):
            return []

        out: list[Lesson] = []
        for raw in raw_lessons[:8]:
            if not isinstance(raw, dict):
                continue
            ltype = str(raw.get("type") or "pattern").strip()
            subject = str(raw.get("subject") or "").strip()
            evidence = str(raw.get("evidence") or "").strip()
            recommendation = str(raw.get("recommended_action") or "").strip()
            try:
                conf = float(raw.get("confidence", 0.6))
            except (TypeError, ValueError):
                conf = 0.6
            if not subject and not evidence:
                continue
            out.append(Lesson(
                type=f"llm:{ltype}",
                subject=subject or "general",
                evidence=evidence or "(no evidence text)",
                confidence=max(0.0, min(1.0, conf)),
                recommended_action=recommendation,
                extra={"source": "llm"},
            ))
        return out

    def _get_llm(self) -> Any:
        """Lazily resolve the LLM adapter, preferring the injected one."""
        if self._llm is not None:
            return self._llm
        try:
            from core.system.llm_adapter import get_llm
            return get_llm()
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _get_prompt_template(name: str) -> Any:
        try:
            from core.system.prompt_library import get_prompt
            return get_prompt(name)
        except Exception:  # noqa: BLE001
            return None

    # ── Goal revision from lessons ─────────────────────────────

    def _revise_goals_from_lessons(self, lessons: list[Lesson]) -> int:
        """Update GoalManager priorities when a lesson contradicts a
        goal's original evidence.

        - A `regression` lesson on a subject that has an active goal
          → revise that goal *up* (more urgent now).
        - An `improvement` lesson → revise the matching practice goal
          *down* (less urgent — we're getting better).
        - A `weakness` lesson creates urgency; already covered by the
          initial propose_from_self_model flow, so we only revise
          existing goals here.
        """
        if self._goal_manager is None:
            return 0
        try:
            active = self._goal_manager.active()
        except Exception:  # noqa: BLE001
            return 0

        revisions = 0
        for lesson in lessons:
            if lesson.type not in ("regression", "improvement"):
                continue
            for goal in active:
                if not isinstance(goal, dict):
                    continue
                source = goal.get("source", "")
                if lesson.subject not in source:
                    continue
                if lesson.type == "regression":
                    new_urgency = min(1.0, float(goal.get("urgency", 0.5)) + 0.3)
                    self._goal_manager.revise(
                        goal["id"],
                        urgency=new_urgency,
                        why=f"reflection: regression detected in {lesson.subject}",
                    )
                else:  # improvement
                    new_urgency = max(0.0, float(goal.get("urgency", 0.5)) - 0.2)
                    self._goal_manager.revise(
                        goal["id"],
                        urgency=new_urgency,
                        why=f"reflection: improvement in {lesson.subject}",
                    )
                revisions += 1
        return revisions

    # ── Lessons → new goals ───────────────────────────────────

    # Lesson types that should spawn fresh goals (vs only revising
    # existing ones). Each maps to (goal_template, urgency, impact).
    _LESSON_TO_GOAL: dict[str, tuple[str, float, float]] = {
        "weakness":   ("Improve {subject}",       0.70, 0.60),
        "regression": ("Recover {subject}",       0.85, 0.70),
        "pattern":    ("Investigate {subject}",   0.55, 0.55),
        "blind_spot": ("Explore {subject}",       0.45, 0.50),
    }
    _GOAL_PROPOSAL_MIN_CONFIDENCE = 0.55
    _GOAL_PROPOSAL_MAX_PER_PASS = 3

    def _propose_goals_from_lessons(self, lessons: list[Lesson]) -> list[str]:
        """Spawn brand-new goals from high-confidence lessons.

        Reflection's revise() path only nudges *existing* goals. This
        complementary path is what lets reflection actually grow the
        goal set:

          - weakness/regression  → "improve/recover X"  (urgent)
          - pattern              → "investigate X"      (medium)
          - blind_spot           → "explore X"          (low)

        Caps to ``_GOAL_PROPOSAL_MAX_PER_PASS`` per call so a single
        noisy reflection can't flood the goal queue, and skips any
        subject already covered by an active goal (matched via the
        goal's ``source`` field, same convention as
        ``GoalManager.propose_from_self_model``).
        """
        if self._goal_manager is None:
            return []

        try:
            active = self._goal_manager.active() or []
        except Exception:  # noqa: BLE001
            active = []

        # Build a fast lookup of subjects already covered by an
        # active goal. We match on the substring after the colon in
        # the source tag (e.g. "self_model.weakness:engine.broken"
        # → "engine.broken") to mirror existing conventions.
        covered: set[str] = set()
        for g in active:
            if not isinstance(g, dict):
                continue
            src = str(g.get("source", "") or "")
            if ":" in src:
                covered.add(src.split(":", 1)[1].strip())
            elif src:
                covered.add(src.strip())

        # Sort lessons by confidence so the highest-signal ones win
        # the per-pass budget.
        candidates = sorted(
            (l for l in lessons
             if l.type in self._LESSON_TO_GOAL
             and l.confidence >= self._GOAL_PROPOSAL_MIN_CONFIDENCE
             and l.subject),
            key=lambda l: l.confidence,
            reverse=True,
        )

        created: list[str] = []
        for lesson in candidates:
            if len(created) >= self._GOAL_PROPOSAL_MAX_PER_PASS:
                break
            if lesson.subject in covered:
                continue
            template, urgency, impact = self._LESSON_TO_GOAL[lesson.type]
            try:
                gid = self._goal_manager.propose(
                    template.format(subject=lesson.subject),
                    why=lesson.evidence[:200] or f"reflection: {lesson.type}",
                    source=f"reflection.{lesson.type}:{lesson.subject}",
                    urgency=urgency,
                    impact=impact,
                    confidence=float(lesson.confidence),
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "Reflection goal proposal failed for %s: %s",
                    lesson.subject, exc,
                )
                continue
            created.append(gid)
            covered.add(lesson.subject)

        if created:
            logger.info(
                "Reflection proposed %d new goals from lessons",
                len(created),
            )
        return created

    # ── Narrative ──────────────────────────────────────────────

    @staticmethod
    def _make_narrative(
        lessons: list[Lesson], episode_count: int,
    ) -> str:
        if not lessons:
            return (
                f"I reviewed {episode_count} episode(s) and found nothing "
                "unusual. No lessons this round."
            )

        counts = Counter(l.type for l in lessons)
        parts = [
            f"I reviewed {episode_count} episode(s) and found {len(lessons)} lesson(s):"
        ]
        for t in ("improvement", "strength", "pattern",
                  "regression", "weakness", "blind_spot"):
            if counts.get(t):
                parts.append(f"{counts[t]} {t}")
        summary = ", ".join(parts[1:])
        header = parts[0]

        # Add top 2 most-confident lessons verbatim
        top = sorted(lessons, key=lambda l: l.confidence, reverse=True)[:2]
        highlights = " ".join(f"[{l.type}] {l.evidence}." for l in top)

        return f"{header} {summary}. {highlights}".strip()


# ── Singleton accessor (optional — callers may also instantiate directly) ──

_instance: Optional[Reflection] = None


def get_reflection(
    *,
    memory: Any = None,
    self_model: Any = None,
    goal_manager: Any = None,
) -> Reflection:
    """Return a lazily-constructed singleton. Pass bindings on first
    call; later calls return the same instance regardless of args."""
    global _instance
    if _instance is None:
        _instance = Reflection(
            memory=memory,
            self_model=self_model,
            goal_manager=goal_manager,
        )
    return _instance
