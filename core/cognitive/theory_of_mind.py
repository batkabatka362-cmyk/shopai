"""TheoryOfMind — modeling external agents (customers, competitors).

Where SelfModel answers "what am I?", TheoryOfMind answers "what
are they?". For each external agent — a customer segment, a
competitor store, an upstream supplier — the AI maintains a small
belief set:

    traits        descriptive {key: value} attributes the AI
                  believes are true (e.g. price_sensitivity=0.7)
    beliefs       hypotheses with confidence in [0, 1] that get
                  reinforced or weakened by observations
    predictions   stored "if I do X, this agent will probably do Y"
                  expectations the AI can later test against reality

The point is to make the AI think about *others*, not just itself.
A pricing decision shouldn't just optimize the AI's own margin —
it should consider how the customer segment will react and how
competitors might respond.

This is heuristic + belief-update. No LLM required (though the
predict() API can be wrapped with one if available).

Storage: SQLite via the existing migration framework. Two tables:

    agents          one row per agent (customer segment, competitor)
    observations    append-only log of every observation that
                    contributed to a belief

Belief update rule (simple Bayesian-ish):

    new_confidence = old_confidence + delta
    delta = +0.1 if observation supports the belief
          = -0.15 if it contradicts (asymmetric — easier to lose
                  trust than to gain it)
    Clamped to [0.05, 0.95] so a belief is never absolute.

The AI's mind module (Phase 4) consults TheoryOfMind during the
goal-setting and planning phases:

    "Will this segment respond well to a discount?"
    "Will this competitor undercut us if we raise prices?"
    "Has this customer's behavior shifted recently?"
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from utils.logger import get_logger

logger = get_logger("cognitive.theory_of_mind")

_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "theory_of_mind.db"


# ── Agent kinds ───────────────────────────────────────────────

KIND_CUSTOMER = "customer"
KIND_COMPETITOR = "competitor"
KIND_SUPPLIER = "supplier"
KIND_PARTNER = "partner"

VALID_KINDS = frozenset({KIND_CUSTOMER, KIND_COMPETITOR, KIND_SUPPLIER, KIND_PARTNER})


# ── Belief update parameters ──────────────────────────────────

_SUPPORT_DELTA = 0.10
_CONTRADICT_DELTA = -0.15
_BELIEF_FLOOR = 0.05
_BELIEF_CEILING = 0.95


def _v1_initial_schema(conn: sqlite3.Connection) -> None:
    """v1: agents + observations tables."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS agents (
            id              TEXT PRIMARY KEY,
            kind            TEXT NOT NULL,
            name            TEXT NOT NULL,
            traits          TEXT DEFAULT '{}',
            beliefs         TEXT DEFAULT '{}',
            observation_count INTEGER DEFAULT 0,
            first_seen      REAL NOT NULL,
            last_seen       REAL NOT NULL,
            updated_at      REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS observations (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id        TEXT NOT NULL,
            kind            TEXT NOT NULL,
            content         TEXT DEFAULT '{}',
            supports        TEXT DEFAULT '',
            contradicts     TEXT DEFAULT '',
            timestamp       REAL NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_agents_kind ON agents(kind);
        CREATE INDEX IF NOT EXISTS idx_obs_agent ON observations(agent_id);
        CREATE INDEX IF NOT EXISTS idx_obs_ts ON observations(timestamp);
    """)


_MIGRATIONS: list[tuple[int, str, Any]] = [
    (1, "initial schema", _v1_initial_schema),
]
_SCHEMA_VERSION = max(m[0] for m in _MIGRATIONS)


@dataclass
class Agent:
    """An external agent the AI is modeling."""
    id: str
    kind: str
    name: str
    traits: dict[str, Any] = field(default_factory=dict)
    beliefs: dict[str, float] = field(default_factory=dict)  # belief → confidence
    observation_count: int = 0
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "traits": dict(self.traits),
            "beliefs": dict(self.beliefs),
            "observation_count": self.observation_count,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
        }

    def top_beliefs(self, n: int = 3) -> list[tuple[str, float]]:
        return sorted(self.beliefs.items(), key=lambda x: x[1], reverse=True)[:n]


@dataclass
class Prediction:
    """A predicted response from an agent given a hypothetical action."""
    agent_id: str
    action_proposed: str
    predicted_response: str
    confidence: float
    supporting_beliefs: list[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "action_proposed": self.action_proposed,
            "predicted_response": self.predicted_response,
            "confidence": round(self.confidence, 3),
            "supporting_beliefs": list(self.supporting_beliefs),
            "notes": self.notes,
        }


class TheoryOfMind:
    """The AI's beliefs about other agents."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        llm: Any = None,
        use_llm: bool = True,
    ) -> None:
        self._db_path = str(db_path or _DB_PATH)
        self._local = threading.local()
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        self._llm = llm
        self._use_llm = bool(use_llm)

    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "c") or self._local.c is None:
            self._local.c = sqlite3.connect(self._db_path, timeout=10)
            self._local.c.row_factory = sqlite3.Row
            self._local.c.execute("PRAGMA journal_mode=WAL")
        return self._local.c

    def _init_schema(self) -> None:
        from core.db.migrations import Migrator, register_schema
        Migrator(self._conn(), "theory_of_mind", _MIGRATIONS).run()
        register_schema("theory_of_mind", Path(self._db_path), _SCHEMA_VERSION)

    # ── Agent registration ────────────────────────────────────

    def register_agent(
        self,
        agent_id: str,
        kind: str,
        name: str,
        *,
        traits: Optional[dict[str, Any]] = None,
        initial_beliefs: Optional[dict[str, float]] = None,
    ) -> Agent:
        """Add a new agent to the model.

        Re-registering the same id is a no-op (returns the existing
        agent). Use update_traits() to add fields incrementally.
        """
        if not agent_id:
            raise ValueError("agent_id required")
        if kind not in VALID_KINDS:
            raise ValueError(f"unknown kind {kind!r}; must be one of {sorted(VALID_KINDS)}")

        existing = self.get_agent(agent_id)
        if existing:
            return existing

        now = time.time()
        agent = Agent(
            id=agent_id,
            kind=kind,
            name=name or agent_id,
            traits=dict(traits or {}),
            beliefs={
                k: max(_BELIEF_FLOOR, min(_BELIEF_CEILING, float(v)))
                for k, v in (initial_beliefs or {}).items()
            },
            first_seen=now,
            last_seen=now,
        )
        conn = self._conn()
        conn.execute(
            "INSERT INTO agents (id, kind, name, traits, beliefs, "
            "    observation_count, first_seen, last_seen, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?)",
            (
                agent.id, agent.kind, agent.name,
                json.dumps(agent.traits),
                json.dumps(agent.beliefs),
                now, now, now,
            ),
        )
        conn.commit()
        logger.info("Agent registered: %s [%s] %s", agent.id, agent.kind, agent.name)
        return agent

    def get_agent(self, agent_id: str) -> Optional[Agent]:
        row = self._conn().execute(
            "SELECT * FROM agents WHERE id = ?", (agent_id,),
        ).fetchone()
        return self._row_to_agent(row) if row else None

    def list_agents(self, kind: Optional[str] = None) -> list[Agent]:
        if kind:
            rows = self._conn().execute(
                "SELECT * FROM agents WHERE kind = ? "
                "ORDER BY last_seen DESC",
                (kind,),
            ).fetchall()
        else:
            rows = self._conn().execute(
                "SELECT * FROM agents ORDER BY last_seen DESC",
            ).fetchall()
        return [self._row_to_agent(r) for r in rows]

    def update_traits(self, agent_id: str, traits: dict[str, Any]) -> None:
        """Merge new traits into the agent. Existing keys are overwritten."""
        agent = self.get_agent(agent_id)
        if agent is None:
            return
        merged = dict(agent.traits)
        merged.update(traits)
        self._conn().execute(
            "UPDATE agents SET traits = ?, updated_at = ? WHERE id = ?",
            (json.dumps(merged), time.time(), agent_id),
        )
        self._conn().commit()

    # ── Observations + belief updates ─────────────────────────

    def observe(
        self,
        agent_id: str,
        content: dict[str, Any],
        *,
        supports: Optional[list[str]] = None,
        contradicts: Optional[list[str]] = None,
    ) -> None:
        """Record an observation about an agent.

        Each observation can support and/or contradict named beliefs.
        Supported beliefs gain confidence (+_SUPPORT_DELTA), contradicted
        ones lose confidence (-_CONTRADICT_DELTA — note the asymmetry).
        New beliefs are auto-created at the floor + a small bump.
        """
        agent = self.get_agent(agent_id)
        if agent is None:
            return

        now = time.time()
        supports = supports or []
        contradicts = contradicts or []

        # Update beliefs
        new_beliefs = dict(agent.beliefs)
        for belief in supports:
            current = new_beliefs.get(belief, _BELIEF_FLOOR)
            new_beliefs[belief] = min(_BELIEF_CEILING, current + _SUPPORT_DELTA)
        for belief in contradicts:
            current = new_beliefs.get(belief, _BELIEF_CEILING)
            new_beliefs[belief] = max(_BELIEF_FLOOR, current + _CONTRADICT_DELTA)

        conn = self._conn()
        conn.execute(
            "UPDATE agents SET beliefs = ?, observation_count = observation_count + 1, "
            "    last_seen = ?, updated_at = ? WHERE id = ?",
            (json.dumps(new_beliefs), now, now, agent_id),
        )
        conn.execute(
            "INSERT INTO observations (agent_id, kind, content, supports, contradicts, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                agent_id, agent.kind,
                json.dumps(content, default=str),
                json.dumps(supports),
                json.dumps(contradicts),
                now,
            ),
        )
        conn.commit()

    def belief(self, agent_id: str, key: str) -> float:
        """Look up a single belief's current confidence."""
        agent = self.get_agent(agent_id)
        if agent is None:
            return 0.0
        return float(agent.beliefs.get(key, 0.0))

    def beliefs(self, agent_id: str) -> dict[str, float]:
        """Return all beliefs for an agent."""
        agent = self.get_agent(agent_id)
        if agent is None:
            return {}
        return dict(agent.beliefs)

    def observation_log(
        self, agent_id: str, limit: int = 50,
    ) -> list[dict[str, Any]]:
        rows = self._conn().execute(
            "SELECT * FROM observations WHERE agent_id = ? "
            "ORDER BY timestamp DESC LIMIT ?",
            (agent_id, limit),
        ).fetchall()
        defaults = {"content": "{}", "supports": "[]", "contradicts": "[]"}
        out = []
        for r in rows:
            d = dict(r)
            for jkey, default in defaults.items():
                raw = d.get(jkey)
                if not raw:
                    raw = default
                try:
                    d[jkey] = json.loads(raw)
                except json.JSONDecodeError:
                    d[jkey] = json.loads(default)
            out.append(d)
        return out

    # ── Prediction ────────────────────────────────────────────

    def predict_response(
        self,
        agent_id: str,
        action: str,
        *,
        belief_rules: Optional[dict[str, dict[str, str]]] = None,
        prefer_llm: Optional[bool] = None,
    ) -> Optional[Prediction]:
        """Predict how an agent will respond to a hypothetical action.

        When an LLM is available, the LLM predictor runs first and
        produces a richer, reasoning-backed prediction. On any LLM
        failure (or when no LLM is wired) the rule-based predictor
        runs as a deterministic fallback.

        Args:
            agent_id: who we're predicting about
            action: a short verb + object string, e.g. "lower price 10%"
            belief_rules: optional mapping override for the rule layer
            prefer_llm: override the instance-level use_llm toggle for
                this call (None = use instance default)

        Returns the highest-confidence prediction, or None if no
        belief weights in to the action.
        """
        agent = self.get_agent(agent_id)
        if agent is None:
            return None

        # ── LLM path (preferred when available) ──
        try_llm = prefer_llm if prefer_llm is not None else self._use_llm
        if try_llm:
            llm_pred = self._llm_predict(agent, action)
            if llm_pred is not None:
                return llm_pred

        # ── Rule-based fallback ──
        rules = belief_rules or _DEFAULT_BELIEF_RULES
        action_lower = action.lower()

        # Find rules that match this action
        matched_belief_map: dict[str, str] = {}
        for action_key, belief_map in rules.items():
            if action_key in action_lower:
                matched_belief_map.update(belief_map)

        if not matched_belief_map:
            return None

        # Score each candidate response by sum of matching belief
        # confidences. The highest-scoring response wins.
        scores: dict[str, float] = {}
        supporting: dict[str, list[str]] = {}
        for belief_name, predicted_response in matched_belief_map.items():
            conf = float(agent.beliefs.get(belief_name, 0.0))
            if conf <= 0:
                continue
            scores[predicted_response] = scores.get(predicted_response, 0.0) + conf
            supporting.setdefault(predicted_response, []).append(belief_name)

        if not scores:
            return None

        best_response = max(scores.items(), key=lambda x: x[1])[0]
        # Normalize confidence: average of contributing beliefs
        contributors = supporting[best_response]
        avg_conf = scores[best_response] / max(1, len(contributors))

        return Prediction(
            agent_id=agent_id,
            action_proposed=action,
            predicted_response=best_response,
            confidence=avg_conf,
            supporting_beliefs=contributors,
            notes=(
                f"matched {len(contributors)} belief(s) "
                f"for action keyword(s)"
            ),
        )

    def stats(self) -> dict[str, Any]:
        rows = self._conn().execute(
            "SELECT kind, COUNT(*) as n, SUM(observation_count) as obs "
            "FROM agents GROUP BY kind",
        ).fetchall()
        return {
            "by_kind": {r["kind"]: int(r["n"]) for r in rows},
            "total_agents": sum(int(r["n"]) for r in rows),
            "total_observations": sum(int(r["obs"] or 0) for r in rows),
        }

    # ── Internals ─────────────────────────────────────────────

    @staticmethod
    def _row_to_agent(row: sqlite3.Row) -> Agent:
        try:
            traits = json.loads(row["traits"] or "{}")
        except json.JSONDecodeError:
            traits = {}
        try:
            beliefs = json.loads(row["beliefs"] or "{}")
        except json.JSONDecodeError:
            beliefs = {}
        return Agent(
            id=row["id"],
            kind=row["kind"],
            name=row["name"] or row["id"],
            traits=traits,
            beliefs={k: float(v) for k, v in beliefs.items()},
            observation_count=int(row["observation_count"] or 0),
            first_seen=float(row["first_seen"]),
            last_seen=float(row["last_seen"]),
        )


# ── LLM predictor (instance methods patched on the class) ────


def _tom_llm_predict(self, agent: Agent, action: str) -> Optional[Prediction]:
    """Ask the LLM to predict an agent's response.

    Renders the centralized `theory_of_mind.predict_response`
    prompt with the agent's traits and beliefs and parses a
    structured JSON response. Returns None on any failure so the
    caller falls back to the rule-based predictor.
    """
    llm = self._get_llm()
    if llm is None:
        return None
    try:
        if not llm.is_available():
            return None
    except Exception:  # noqa: BLE001
        return None

    try:
        from core.system.prompt_library import get_prompt
    except Exception:  # noqa: BLE001
        return None
    template = get_prompt("theory_of_mind.predict_response")
    if template is None:
        return None

    # Format traits/beliefs as compact JSON for the prompt
    try:
        traits_str = json.dumps(agent.traits, default=str)[:500]
        beliefs_str = json.dumps({
            k: round(v, 2) for k, v in agent.beliefs.items()
        })[:500]
    except Exception:  # noqa: BLE001
        return None

    rendered = template.render(
        agent_name=agent.name,
        agent_kind=agent.kind,
        agent_traits=traits_str,
        agent_beliefs=beliefs_str,
        action=action,
    )

    try:
        structured = llm.ask_structured(
            role=template.role,
            prompt=rendered.user,
            system_prompt=rendered.system,
            schema_hint=template.schema_hint,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("ToM LLM call failed: %s", exc)
        return None

    if not getattr(structured, "ok", False):
        return None

    data = structured.data or {}
    response = str(data.get("predicted_response") or "").strip()
    if not response:
        return None

    try:
        conf = max(0.0, min(1.0, float(data.get("confidence", 0.5))))
    except (TypeError, ValueError):
        conf = 0.5

    reasoning = str(data.get("reasoning") or "")[:300]
    alternatives = data.get("alternative_responses") or []
    alt_summary = ""
    if isinstance(alternatives, list) and alternatives:
        alt_parts = []
        for alt in alternatives[:3]:
            if isinstance(alt, dict):
                r = alt.get("response", "")
                p = alt.get("probability", "")
                if r:
                    alt_parts.append(f"{r}({p})")
        if alt_parts:
            alt_summary = " alts: " + ", ".join(alt_parts)

    return Prediction(
        agent_id=agent.id,
        action_proposed=action,
        predicted_response=response,
        confidence=conf,
        supporting_beliefs=["llm"],
        notes=(reasoning + alt_summary).strip(),
    )


def _tom_get_llm(self) -> Any:
    """Lazily resolve the LLM adapter."""
    if self._llm is not None:
        return self._llm
    try:
        from core.system.llm_adapter import get_llm
        return get_llm()
    except Exception:  # noqa: BLE001
        return None


# Patch onto the class
TheoryOfMind._llm_predict = _tom_llm_predict
TheoryOfMind._get_llm = _tom_get_llm


# ── Default belief → response rules ──────────────────────────
#
# Each entry maps an action substring (case-insensitive) to a dict
# of {belief_name: predicted_response}. If the agent has any of
# the beliefs and they're nonzero, predict_response() picks the
# highest-confidence one.

_DEFAULT_BELIEF_RULES: dict[str, dict[str, str]] = {
    "lower price": {
        "price_sensitive": "buy_more",
        "loyal": "buy_more",
        "skeptical": "wait_for_more",
    },
    "raise price": {
        "price_sensitive": "switch_to_competitor",
        "loyal": "buy_anyway",
        "premium_seeker": "buy_anyway",
    },
    "discount": {
        "price_sensitive": "convert",
        "deal_hunter": "convert",
        "loyal": "convert",
        "skeptical": "ignore",
    },
    "premium product": {
        "premium_seeker": "engage",
        "price_sensitive": "ignore",
        "deal_hunter": "ignore",
    },
    "free shipping": {
        "cart_abandoner": "complete_checkout",
        "price_sensitive": "complete_checkout",
    },
}


# ── Singleton accessor ────────────────────────────────────────


_instance: Optional[TheoryOfMind] = None
_instance_lock = threading.Lock()


def get_theory_of_mind() -> TheoryOfMind:
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = TheoryOfMind()
    return _instance
